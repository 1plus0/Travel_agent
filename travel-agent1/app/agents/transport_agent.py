from typing import Dict, List, Optional
import asyncio

from app.agents.base import get_model
from app.tools.mcp_tools import MCPTransportClient
from app.tools.variflight_mcp_tools import VariflightMCPClient
from app.tools.city_codes import to_iata_city_code


class TransportAgent:
    """交通比价智能体"""

    def __init__(self):
        self.llm = get_model(temperature=0.1)
        self.mcp_client = MCPTransportClient()
        self.variflight_client = VariflightMCPClient()

    async def get_transport_plan(
        self,
        departure: str,
        destination: str,
        date: str,
        transport_types: Optional[List[str]] = None,
    ) -> Dict:
        if transport_types is None:
            transport_types = ["train", "flight"]

        results: Dict[str, object] = {}

        tasks = []
        task_names = []

        if "train" in transport_types:
            tasks.append(self._get_train_info(departure, destination, date))
            task_names.append("train")

        if "flight" in transport_types:
            tasks.append(self._get_flight_info(departure, destination, date))
            task_names.append("flight")

        query_results = await asyncio.gather(*tasks, return_exceptions=True)

        for name, r in zip(task_names, query_results):
            if isinstance(r, Exception):
                results[name] = {"source": "agent", "error": str(r)}
            else:
                results[name] = r

        analysis = await self._analyze_transport_options(results, departure, destination)

        return {
            "departure": departure,
            "destination": destination,
            "date": date,
            "options": results,
            "analysis": analysis,
        }

    async def _get_train_info(self, departure: str, destination: str, date: str) -> Dict:
        r = await self.mcp_client.query_12306_trains(departure, destination, date)
        if not r.get("success"):
            return {"source": "12306-mcp", "error": r.get("error"), "raw": r.get("raw"), "meta": r.get("meta")}
        return {"source": "12306-mcp", "raw": r.get("data"), "summary": r.get("summary"), "meta": r.get("meta")}

    async def _get_flight_info(self, departure: str, destination: str, date: str) -> Dict:
        dep_code = to_iata_city_code(departure)
        arr_code = to_iata_city_code(destination)

        if not dep_code or not arr_code:
            return {
                "source": "variflight-mcp",
                "error": f"航班查询需要 IATA 三字码城市码，无法从输入解析：{departure} -> {destination}",
                "hint": "示例：北京=BJS，上海=SHA。你也可以直接输入三字码。",
            }

        r = await self.variflight_client.search_flight_itineraries(dep_code, arr_code, date)
        if not r.get("success"):
            return {"source": "variflight-mcp", "error": r.get("error"), "raw": r.get("raw"), "meta": r.get("meta")}

        return {"source": "variflight-mcp", "raw": r.get("data"), "meta": r.get("meta"), "query": {"depCityCode": dep_code, "arrCityCode": arr_code, "depDate": date}}

    async def _analyze_transport_options(self, transport_data: Dict, departure: str, destination: str) -> str:
        # 先做一个保底：没有任何可用结果就直接返回
        if not transport_data:
            return "未获取到交通数据。"

        # 控制长度：避免 flight raw 过大
        compact = {}
        for k, v in transport_data.items():
            if not isinstance(v, dict):
                compact[k] = v
                continue
            vv = dict(v)
            raw = vv.get("raw")
            if isinstance(raw, list):
                vv["raw"] = raw[:10]
            compact[k] = vv

        prompt = f"""
你是交通比价助手。严格规则：
- 只能基于“交通数据”中给出的内容做结论；禁止使用常识/经验补全价格、时长、车次/航班号。
- 如果某种交通方式缺失或只有 error，请明确写“数据缺失/查询失败”，并给出下一步建议（例如让用户开启该交通类型或检查城市/日期）。
输出：
1) 火车推荐（最快/最省/综合）若有数据
2) 飞机推荐（最快/最省/综合）若有数据
3) 仅基于数据的对比建议（到站/机场信息若数据未给出则不要写）
出发地：{departure}
目的地：{destination}
交通数据：
{compact}
"""
        try:
            resp = await self.llm.ainvoke(prompt)
            return getattr(resp, "content", str(resp))
        except Exception as e:
            return f"分析失败：{e}"