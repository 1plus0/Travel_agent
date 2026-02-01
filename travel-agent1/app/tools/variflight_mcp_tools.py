from __future__ import annotations

from typing import Any, Dict

from app.core.config import settings
from app.tools.mcp_base import BaseMCPClient
from app.tools.variflight_summary import parse_variflight_summary


class VariflightMCPClient(BaseMCPClient):
    def __init__(self):
        super().__init__(settings.MCP_VARIFLIGHT_REMOTE_URL)

    async def search_flight_itineraries(self, dep_city_code: str, arr_city_code: str, dep_date: str) -> Dict[str, Any]:
        r = await self.call_tool(
            "searchFlightItineraries",
            {"depCityCode": dep_city_code, "arrCityCode": arr_city_code, "depDate": dep_date},
        )
        if not r.get("success"):
            return r

        result_obj = self._extract_result_json(r.get("data", {}))

        # 统一拿到“中文摘要文本”
        if isinstance(result_obj, dict) and isinstance(result_obj.get("data"), str):
            raw_text = result_obj["data"]
        elif isinstance(result_obj, str):
            raw_text = result_obj
        else:
            raw_text = str(result_obj)

        summary = parse_variflight_summary(raw_text)

        return {"success": True, "data": result_obj, "raw_text": raw_text, "summary": summary, "meta": r.get("meta")}