from __future__ import annotations

from typing import Any, Dict, Optional  # 删除 List

from app.core.config import settings
from app.tools.mcp_base import BaseMCPClient


def _pick_station_code(v: Any) -> Optional[str]:
    """把 station 相关返回统一成 station_code 字符串。"""
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s or None
    if isinstance(v, dict):
        for k in ("station_code", "stationCode", "code", "telecode", "station_telecode", "stationTelecode"):
            val = v.get(k)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return None
    return None


class MCPTransportClient(BaseMCPClient):
    """MCP交通工具客户端（用于本地 12306-mcp 的 Streamable HTTP 接口）"""

    def __init__(self):
        super().__init__(settings.MCP_12306_REMOTE_URL)  # 例如 http://127.0.0.1:8080/mcp

    async def query_12306_trains(self, departure: str, destination: str, date: str) -> Dict[str, Any]:
        """
        返回结构：
        { success: bool, data: list|..., summary: {...}, meta: {...} }
        """
        # 1) 城市 -> station_code（代表站）
        codes = await self.call_tool("get-station-code-of-citys", {"citys": f"{departure}|{destination}"})
        if not codes.get("success"):
            return codes

        codes_result = self._extract_result_json(codes.get("data", {}))
        if not isinstance(codes_result, dict):
            return {"success": False, "error": "站点代码返回格式异常", "raw": codes_result, "meta": codes.get("meta")}

        # 兼容返回：{"citys":[{"city":"北京","station_code":"BJP"}, ...]}
        from_code = None
        to_code = None
        if isinstance(codes_result.get("citys"), list):
            m = {x.get("city"): x for x in codes_result["citys"] if isinstance(x, dict)}
            from_code = _pick_station_code(m.get(departure))
            to_code = _pick_station_code(m.get(destination))
        else:
            # 兜底：可能直接返回 {"北京": {...}, "上海": {...}} 或 {"from": "..."}
            from_code = _pick_station_code(codes_result.get("fromStation") or codes_result.get("from") or codes_result.get(departure))
            to_code = _pick_station_code(codes_result.get("toStation") or codes_result.get("to") or codes_result.get(destination))

        if not from_code or not to_code:
            return {"success": False, "error": "无法解析代表站 station_code", "raw": codes_result, "meta": codes.get("meta")}

        async def _get_tickets(fc: str, tc: str) -> Dict[str, Any]:
            r = await self.call_tool(
                "get-tickets",
                {
                    "date": date,
                    "fromStation": fc,
                    "toStation": tc,
                    "format": "json",
                    # 你也可以在这里加筛选/排序/时间窗等参数
                    # "trainFilterFlags": "GD",
                    # "sortFlag": "duration",
                    # "limitedNum": 30,
                },
            )
            if not r.get("success"):
                return r

            result_obj = self._extract_result_json(r.get("data", {}))
            trains = None
            if isinstance(result_obj, list):
                trains = result_obj
            elif isinstance(result_obj, dict):
                # 有些实现把列表放在 data 字段里
                trains = result_obj.get("data") if isinstance(result_obj.get("data"), list) else None
            if trains is None:
                trains = []

            return {
                "success": True,
                "data": trains,
                "summary": _summarize_trains(trains),
                "meta": {
                    "fromStation": fc,
                    "toStation": tc,
                    "date": date,
                    "content_type": (r.get("meta") or {}).get("content_type"),
                },
            }

        # 2) 先查代表站
        first = await _get_tickets(from_code, to_code)
        if not first.get("success"):
            return first
        if first.get("data"):
            first.setdefault("meta", {})
            first["meta"]["fallback"] = "representative_station"
            return first

        # 3) 空结果：回退城市内站点组合（限制数量避免爆炸）
        dep_stations = await self.call_tool("get-stations-code-in-city", {"city": departure})
        arr_stations = await self.call_tool("get-stations-code-in-city", {"city": destination})
        if not dep_stations.get("success") or not arr_stations.get("success"):
            first.setdefault("meta", {})
            first["meta"]["fallback"] = "failed_to_get_city_stations"
            return first

        dep_list = self._extract_result_json(dep_stations.get("data", {}))
        arr_list = self._extract_result_json(arr_stations.get("data", {}))
        if not isinstance(dep_list, list) or not isinstance(arr_list, list):
            first.setdefault("meta", {})
            first["meta"]["fallback"] = "city_stations_format_invalid"
            return first

        dep_list = dep_list[:5]
        arr_list = arr_list[:5]

        for ds in dep_list:
            fc = _pick_station_code(ds)
            if not fc:
                continue
            for ts in arr_list:
                tc = _pick_station_code(ts)
                if not tc:
                    continue
                r = await _get_tickets(fc, tc)
                if r.get("success") and r.get("data"):
                    r.setdefault("meta", {})
                    r["meta"]["fallback"] = "tried_top5_city_stations"
                    return r

        first.setdefault("meta", {})
        first["meta"]["fallback"] = "tried_top5_city_stations_but_empty"
        return first


def _seat_available(num: Any) -> bool:
    if num is None:
        return False
    if isinstance(num, (int, float)):
        return num > 0
    s = str(num).strip()
    if s in ("无", "--", "0", ""):
        return False
    if s == "有":
        return True
    try:
        return float(s) > 0
    except Exception:
        return False


def _summarize_trains(trains: Any) -> Dict[str, Any]:
    if not isinstance(trains, list):
        return {"count": 0, "min_price": None, "available_train_count": 0}

    min_price: Optional[float] = None
    available_train_count = 0

    for t in trains:
        if not isinstance(t, dict):
            continue

        prices = t.get("prices")
        if not isinstance(prices, list):
            continue

        train_has_any_seat = False

        for p in prices:
            if not isinstance(p, dict):
                continue
            if not _seat_available(p.get("num")):
                continue

            train_has_any_seat = True

            price_val = p.get("price")
            if price_val is None:
                continue
            try:
                pv = float(price_val)
            except Exception:
                continue
            if min_price is None or pv < min_price:
                min_price = pv

        if train_has_any_seat:
            available_train_count += 1

    return {"count": len(trains), "min_price": min_price, "available_train_count": available_train_count}