import os
import math
import json
import time
import requests
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from app.tools.utils import tool_return
from app.core.config import settings
from app.agents.base import get_model

def robust_json_loads(text: str) -> Dict[str, Any]:
    """
    尽可能从模型输出中解析出JSON对象。
    允许：
    - 前后夹杂解释文字
    - ```json ... ```代码块
    - 多余空白
    失败则抛出 ValueError
    """
    if text is None:
        raise ValueError("empty response: None")

    s = text.strip()
    if not s:
        raise ValueError("empty response: blank string")

    # 1) 去掉 ```json ``` 包裹
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)

    # 2) 直接尝试
    try:
        return json.loads(s)
    except Exception:
        pass

    # 3) 尝试从中间提取第一个 { ... } 区间
    start = s.find("{")
    end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = s[start:end+1]
        try:
            return json.loads(candidate)
        except Exception:
            pass

    raise ValueError(f"cannot parse json from model output: {s[:200]}")


class AmapHotelFinder:
    """只负责：位置 -> 坐标 -> 周边酒店 -> 地理分析后的结构化酒店列表"""

    def __init__(self, api_key: str, timeout: int = 12):
        self.api_key = api_key
        self.base_url = "https://restapi.amap.com/v3"
        self.timeout = timeout
        self.geo_cache: Dict[str, Tuple[float, float]] = {}
        self.poi_cache: Dict[str, List[Dict]] = {}

    def find_hotels(self, location: str, radius: int = 2000, max_hotels: int = 20) -> List[Dict]:
        center = self._geocode_location(location)
        if not center:
            return []
        center_lat, center_lon = center

        pois = self._search_nearby_pois(center_lat, center_lon, radius, "酒店", max_hotels)
        if not pois:
            return []

        detailed: List[Dict] = []
        for i, poi in enumerate(pois, 1):
            hotel = self._get_hotel_with_geo_analysis(poi, center_lat, center_lon)
            if hotel:
                detailed.append(hotel)
            if i < len(pois):
                time.sleep(0.08)  # 轻微节流，避免太快
        return detailed

    def _geocode_location(self, location: str) -> Optional[Tuple[float, float]]:
        key = f"geo:{location}"
        if key in self.geo_cache:
            return self.geo_cache[key]

        url = f"{self.base_url}/geocode/geo"
        params = {"key": self.api_key, "address": location, "output": "json"}
        try:
            r = requests.get(url, params=params, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            if data.get("status") == "1" and data.get("geocodes"):
                first = data["geocodes"][0]
                loc = first.get("location", "")
                if loc and "," in loc:
                    lon_s, lat_s = loc.split(",", 1)
                    lat, lon = float(lat_s.strip()), float(lon_s.strip())
                    self.geo_cache[key] = (lat, lon)
                    return (lat, lon)
        except Exception:
            return None
        return None

    def _search_nearby_pois(self, lat: float, lon: float, radius: int, keywords: str, count: int) -> List[Dict]:
        cache_key = f"poi:{lat:.4f},{lon:.4f},{radius},{keywords},{count}"
        if cache_key in self.poi_cache:
            return self.poi_cache[cache_key][:count]

        url = f"{self.base_url}/place/around"
        params = {
            "key": self.api_key,
            "location": f"{lon},{lat}",
            "keywords": keywords,
            "radius": radius,
            "offset": str(min(count, 25)),
            "page": "1",
            "extensions": "base",
            "output": "json",
        }
        try:
            r = requests.get(url, params=params, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            if data.get("status") == "1":
                pois = data.get("pois", []) or []
                valid = [p for p in pois if isinstance(p, dict)]
                self.poi_cache[cache_key] = valid
                return valid[:count]
        except Exception:
            return []
        return []

    def _get_hotel_with_geo_analysis(self, hotel_data: Any, center_lat: float, center_lon: float) -> Dict:
        if not isinstance(hotel_data, dict):
            return {}

        def safe_get(d: Dict, k: str, default: Any = "") -> Any:
            v = d.get(k, default)
            if v is None:
                return default
            if isinstance(v, list):
                return v[0] if v else default
            return v

        hotel = {
            "hotel_id": safe_get(hotel_data, "id"),
            "name": safe_get(hotel_data, "name"),
            "address": safe_get(hotel_data, "address"),
            "tel": safe_get(hotel_data, "tel"),
            "location": safe_get(hotel_data, "location"),  # "lon,lat"
            "type": safe_get(hotel_data, "type"),
            "rating": None,
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        biz_ext = hotel_data.get("biz_ext")
        if isinstance(biz_ext, dict):
            hotel["rating"] = biz_ext.get("rating")

        # 坐标解析
        loc = hotel.get("location") or ""
        if "," in loc:
            try:
                lon_s, lat_s = loc.split(",", 1)
                h_lon, h_lat = float(lon_s.strip()), float(lat_s.strip())
                hotel["subway"] = self._analyze_subway_access(h_lat, h_lon)
                hotel["attractions"] = self._analyze_nearby_attractions(h_lat, h_lon)
                hotel["commercial"] = self._analyze_commercial_facilities(h_lat, h_lon)
                hotel["bus"] = self._analyze_bus_access(h_lat, h_lon)
                hotel["distance_to_center_m"] = int(self._calculate_distance(h_lat, h_lon, center_lat, center_lon))
            except Exception:
                pass

        return hotel

    def _analyze_subway_access(self, lat: float, lon: float, radius: int = 1500) -> Dict:
        subways = self._search_nearby_pois(lat, lon, radius, "地铁站", 3)
        if not subways:
            return {"name": None, "distance_m": None, "walk_min": None}

        nearest = None
        min_d = 10**9
        for s in subways:
            loc = s.get("location", "")
            if "," not in loc:
                continue
            try:
                slon_s, slat_s = loc.split(",", 1)
                slon, slat = float(slon_s.strip()), float(slat_s.strip())
                d = self._calculate_distance(lat, lon, slat, slon)
                if d < min_d:
                    min_d = d
                    nearest = s
            except Exception:
                continue

        if not nearest:
            return {"name": None, "distance_m": None, "walk_min": None}

        walk_min = int(min_d / 1.2 / 60)
        return {
            "name": nearest.get("name"),
            "distance_m": int(min_d),
            "walk_min": walk_min,
        }

    def _analyze_nearby_attractions(self, lat: float, lon: float, radius: int = 2000) -> List[Dict]:
        pois = self._search_nearby_pois(lat, lon, radius, "", 12)
        if not pois:
            return []
        attraction_types = ["风景名胜", "公园广场", "博物馆", "文物古迹", "旅游景点", "景点"]

        out = []
        for p in pois:
            t = p.get("type", "") or ""
            n = p.get("name", "") or ""
            is_attr = any(x in t for x in attraction_types) or ("公园" in n) or ("景区" in n)
            if not is_attr:
                continue
            loc = p.get("location", "")
            if "," not in loc:
                continue
            try:
                plon_s, plat_s = loc.split(",", 1)
                plon, plat = float(plon_s.strip()), float(plat_s.strip())
                d = self._calculate_distance(lat, lon, plat, plon)
                out.append({"name": n, "distance_m": int(d), "type": t})
            except Exception:
                continue
        out.sort(key=lambda x: x["distance_m"])
        return out[:3]

    def _analyze_commercial_facilities(self, lat: float, lon: float, radius: int = 1000) -> Dict:
        def collect(keywords: str, limit: int = 3) -> List[Dict]:
            pois = self._search_nearby_pois(lat, lon, radius, keywords, 8)
            items = []
            for p in pois:
                loc = p.get("location", "")
                d = self._calculate_distance_from_str(lat, lon, loc)
                items.append({"name": p.get("name"), "distance_m": d})
            items.sort(key=lambda x: x["distance_m"])
            return items[:limit]

        return {
            "malls": collect("商场|购物中心"),
            "markets": collect("超市|便利店"),
            "restaurants": collect("餐厅|饭店|美食"),
        }

    def _analyze_bus_access(self, lat: float, lon: float, radius: int = 500) -> Dict:
        pois = self._search_nearby_pois(lat, lon, radius, "公交站", 10)
        names = [p.get("name") for p in pois if isinstance(p, dict) and p.get("name")]
        return {"count_500m": len(names), "nearest": names[0] if names else None}

    def _calculate_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        lat1r, lon1r, lat2r, lon2r = map(math.radians, [lat1, lon1, lat2, lon2])
        dlon = lon2r - lon1r
        dlat = lat2r - lat1r
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))
        return 6371000 * c

    def _calculate_distance_from_str(self, lat1: float, lon1: float, location_str: str) -> int:
        if not location_str or "," not in location_str:
            return 999999
        try:
            lon_s, lat_s = location_str.split(",", 1)
            lon2, lat2 = float(lon_s.strip()), float(lat_s.strip())
            return int(self._calculate_distance(lat1, lon1, lat2, lon2))
        except Exception:
            return 999999


def _compact_hotels(hotels: List[Dict], max_n: int = 20) -> List[Dict]:
    """缩减字段，避免 token 爆炸"""
    out = []
    for h in hotels[:max_n]:
        out.append({
            "name": h.get("name"),
            "address": h.get("address"),
            "rating": h.get("rating"),
            "distance_to_center_m": h.get("distance_to_center_m"),
            "subway": h.get("subway"),
            "attractions": h.get("attractions"),
            "commercial": h.get("commercial"),
            "bus": h.get("bus"),
        })
    return out


def llm_rank_hotels_text(hotels: list[dict], user_type: str, top_n: int, profile_json: str) -> str:
    model = get_model(temperature=0.2)

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "你是资深旅行顾问与酒店选址专家。"
         "你会收到用户画像profile与候选酒店数据。"
         "请基于profile筛选并推荐酒店。不得编造不存在的价格/设施/距离。"
         "只输出纯文本，不要输出JSON，不要输出Markdown代码块。\n\n"
         "输出必须严格遵守以下格式（用中文）：\n"
         "【推荐结论】一段话总结（1-2句）\n"
         "【推荐清单】必须给出TopN={top_n}家，按1..N编号，每家包含：\n"
         "  - 酒店名：xxx\n"
         "  - 位置亮点：地铁/景点/商业/中心距离中至少2条（基于数据）\n"
         "  - 可能的不足：1条（基于数据或信息缺失说明）\n"
         "【下一步我需要确认】最多2个问题，用于推进下一步（例如：是否需要比价/到达方式/偏好住景区还是市区）\n\n"
         "注意：如果候选里没有价格字段，不要声称“更便宜”，只能说“更可能节省通勤成本/更偏经济型位置”，并建议下一步比价。"
        ),
        ("human",
         "用户画像profile(JSON)：{profile_json}\n"
         "用户类型：{user_type}\n"
         "需要推荐TopN：{top_n}\n"
         "候选酒店数据(JSON)：{hotels_json}\n")
    ])

    chain = prompt | model | StrOutputParser()
    text = chain.invoke({
        "profile_json": profile_json or "{}",
        "user_type": user_type,
        "top_n": top_n,
        "hotels_json": json.dumps(hotels, ensure_ascii=False),
    }).strip()

    # 简单兜底：空输出时直接给固定提示
    if not text:
        return (
            "【推荐结论】已获取到附近酒店候选，但模型未返回推荐文本。\n"
            f"【推荐清单】暂无法生成Top{top_n}清单。\n"
            "【下一步我需要确认】你更想住景区附近还是市区更方便？需要我帮你做平台比价吗？"
        )

    return text




@tool
def recommend_hotels_nearby(
    location: str,
    profile_json: str = "",
    radius: int = 2000,
    user_type: str = "综合",
    top_n: int = 6,
    max_hotels: int = 20
) -> str:
    """
    在某个位置附近推荐酒店（高德实时POI + 地理分析 + 大模型总结推荐）。
    返回：tool_return 协议的 JSON 字符串。
    """
    api_key = os.getenv("AMAP_API_KEY", "").strip() or getattr(settings, "AMAP_API_KEY", "")
    if not api_key:
        return tool_return(False, error="未配置 AMAP_API_KEY（环境变量或 settings）", source="amap+llm")

    if not location or not location.strip():
        return tool_return(False, error="location 不能为空", source="amap+llm")

    # 限制范围，避免模型/接口被滥用
    radius = max(300, min(int(radius), 5000))
    top_n = max(1, min(int(top_n), 10))
    max_hotels = max(5, min(int(max_hotels), 30))

    finder = AmapHotelFinder(api_key=api_key, timeout=12)
    hotels = finder.find_hotels(location=location, radius=radius, max_hotels=max_hotels)

    if not hotels:
        return tool_return(False, error="未找到酒店候选（地理编码失败或周边无结果）", source="amap+llm")

    compact = _compact_hotels(hotels, max_n=min(max_hotels, 20))
    text = llm_rank_hotels_text(compact, user_type=user_type, top_n=top_n, profile_json=profile_json)

    data = {
        "query": {"location": location, "radius": radius, "user_type": user_type, "top_n": top_n},
        "text": text,
        "candidates_count": len(hotels),
    }
    return tool_return(True, data=data, source="amap+llm")
