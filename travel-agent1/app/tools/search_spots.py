import os
import requests
from langchain_core.tools import tool
from app.tools.utils import tool_return
from app.core.config import settings

AMAP_API_KEY = settings.AMAP_API_KEY

@tool
def search_hot_scenic_spots(city: str, limit: int = 10) -> str:
    """
    使用高德 POI 文本搜索，获取指定城市的热门景点列表。
    
    参数：
    - city: 城市名称（如“北京”“成都”）
    - limit: 返回数量（建议 1-20）
    
    返回：
    - JSON 字符串，包含 ok/data/error/source/retrieved_at
    """
    # 1) 参数校验（工具不抛异常，直接返回 error）
    if not city or not city.strip():
        return tool_return(False, error="city 不能为空", source="amap")

    if not AMAP_API_KEY:
        return tool_return(False, error="未配置 AMAP_API_KEY 环境变量", source="amap")

    # limit 限制到合理范围
    try:
        limit = int(limit)
    except Exception:
        limit = 10
    limit = max(1, min(limit, 20))

    # 2) 构造请求
    url = "https://restapi.amap.com/v3/place/text"

    # 高德 place/text 常用参数是 offset/page（每页数量/第几页）
    # offset: 1-25（每页条数），page: 1-100
    params = {
        "key": AMAP_API_KEY,
        "keywords": "景点 景区 名胜 古迹",
        "city": city,
        "citylimit": "true",
        "types": "110000",       # 旅游景点
        "offset": str(limit),    # 每页条数
        "page": "1",
        "extensions": "base",
        "output": "JSON",
    }

    # 3) 发送请求并解析
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        result = resp.json()
    except requests.exceptions.RequestException as e:
        return tool_return(False, error=f"网络请求错误: {str(e)}", source="amap")
    except Exception as e:
        return tool_return(False, error=f"响应解析失败: {str(e)}", source="amap")

    # 4) 高德返回 status="1" 才表示成功
    if result.get("status") != "1":
        return tool_return(False, error=f"API调用失败: {result.get('info', '未知错误')}", source="amap")

    pois = result.get("pois", []) or []
    spots = []
    for poi in pois:
        spots.append({
            "name": poi.get("name", ""),
            "address": poi.get("address", ""),
            "adname": poi.get("adname", ""),
            "tel": poi.get("tel", ""),
            # 高德很多 poi 没 rating 字段，保留但不保证有
            "rating": poi.get("rating") if "rating" in poi else None,
            "type": poi.get("type", ""),
            "location": poi.get("location", ""),
        })

    return tool_return(True, data={
        "city": city,
        "limit": limit,
        "count": len(spots),
        "spots": spots
    }, source="amap")
