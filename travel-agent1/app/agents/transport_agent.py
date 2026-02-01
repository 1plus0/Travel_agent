# tools/transport_agent_tool.py
# 交通比价执行Agent（Tool化版本，支持去程 + 返程）
# - 输入：profile_json（UserProfile.to_dict() 后的 JSON 字符串）
# - 关键变化：
#   1) 去程使用 profile.departure_date（YYYY-MM-DD）
#   2) 若 profile.return_date 存在且合法，则自动追加“返程查询”（起终点对换）
# - 输出：tool_return(...) -> str，其中 data.text 为可直接回复用户的纯文本（汇总去/返程）
# - 关键增强：
#   - 火车 502/网络错误重试
#   - 无数据不调用LLM（防幻觉）
#   - options/debug 中带回下游错误与HTTP状态（供主agent需要时展示）

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from app.tools.utils import tool_return  # 你的 tool_return(obj)->str

from app.agents.base import get_model
from app.tools.mcp_tools import MCPTransportClient
from app.tools.variflight_mcp_tools import VariflightMCPClient
from app.tools.city_codes import to_iata_city_code


# -----------------------------
# Utils
# -----------------------------

YYYY_MM_DD_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _safe_json_loads(s: str) -> Dict[str, Any]:
    try:
        return json.loads(s) if s else {}
    except Exception:
        return {}


def _compact_profile(profile_json: str, max_chars: int = 1400) -> str:
    s = (profile_json or "").strip()
    if not s:
        return "{}"
    return s if len(s) <= max_chars else s[:max_chars] + "…(truncated)"


def _run_coro_sync(coro):
    """
    在同步工具函数里安全执行 async 协程。
    - 无running loop：asyncio.run
    - 已有running loop：新建事件循环执行（避免 RuntimeError）
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    new_loop = asyncio.new_event_loop()
    try:
        return new_loop.run_until_complete(coro)
    finally:
        new_loop.close()


def _is_valid_yyyy_mm_dd(s: Any) -> bool:
    return isinstance(s, str) and bool(YYYY_MM_DD_RE.match(s.strip()))


def _is_nonempty_list(x: Any) -> bool:
    return isinstance(x, list) and len(x) > 0


def _extract_raw_len(d: Dict[str, Any]) -> int:
    raw = d.get("raw")
    return len(raw) if isinstance(raw, list) else 0


def _normalize_city(s: Any) -> str:
    return (s or "").strip() if isinstance(s, str) else ""


def parse_transport_args_from_profile(profile_json: str) -> Dict[str, Any]:
    """
    针对你的 UserProfile 结构解析交通参数：
    - depart_city
    - destination
    - departure_date (YYYY-MM-DD)
    - return_date (YYYY-MM-DD)
    """
    p = _safe_json_loads(profile_json)
    departure = _normalize_city(p.get("depart_city"))
    destination = _normalize_city(p.get("destination"))

    departure_date = p.get("departure_date")
    return_date = p.get("return_date")

    dep = departure_date.strip() if isinstance(departure_date, str) else None
    ret = return_date.strip() if isinstance(return_date, str) else None

    return {
        "departure": departure,
        "destination": destination,
        "departure_date": dep,
        "return_date": ret,
        "people": p.get("people"),
        "days": p.get("days"),
        "budget_cny": p.get("budget_cny"),
        "preferences": p.get("preferences"),
    }


# -----------------------------
# Executor
# -----------------------------

@dataclass
class TransportDebug:
    train_ok: bool = False
    flight_ok: bool = False
    train_error: Any = ""
    flight_error: Any = ""
    train_raw_len: int = 0
    flight_raw_len: int = 0
    flight_query: Optional[Dict[str, Any]] = None


class TransportExecutor:
    """交通比价执行器：并发查火车/航班 + LLM总结（仅在有数据时）"""

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
        profile_json: str = "",
        debug: Optional[TransportDebug] = None,
    ) -> Dict[str, Any]:
        if transport_types is None:
            transport_types = ["train", "flight"]

        results: Dict[str, Any] = {}
        tasks = []
        task_names = []

        if "train" in transport_types:
            tasks.append(self._get_train_info_with_retry(departure, destination, date, retries=3))
            task_names.append("train")

        if "flight" in transport_types:
            tasks.append(self._get_flight_info(departure, destination, date))
            task_names.append("flight")

        query_results = await asyncio.gather(*tasks, return_exceptions=True)

        for name, r in zip(task_names, query_results):
            if isinstance(r, Exception):
                results[name] = {"ok": False, "source": "agent", "error": {"type": "exception", "message": str(r)}}
            else:
                results[name] = r

        # debug 填充
        if debug is not None:
            train = results.get("train", {}) if isinstance(results.get("train"), dict) else {}
            flight = results.get("flight", {}) if isinstance(results.get("flight"), dict) else {}

            debug.train_error = train.get("error", "") if isinstance(train, dict) else ""
            debug.flight_error = flight.get("error", "") if isinstance(flight, dict) else ""
            debug.train_raw_len = _extract_raw_len(train) if isinstance(train, dict) else 0
            debug.flight_raw_len = _extract_raw_len(flight) if isinstance(flight, dict) else 0
            debug.train_ok = debug.train_raw_len > 0
            debug.flight_ok = debug.flight_raw_len > 0
            debug.flight_query = flight.get("query") if isinstance(flight, dict) else None

        # 无数据则不调用LLM，避免胡说
        analysis_text = self._no_data_or_error_summary(
            departure=departure,
            destination=destination,
            date=date,
            results=results,
            profile_json=profile_json,
        )
        if analysis_text is None:
            analysis_text = await self._analyze_transport_options_text(
                transport_data=results,
                departure=departure,
                destination=destination,
                date=date,
                profile_json=profile_json,
            )

        return {
            "departure": departure,
            "destination": destination,
            "date": date,
            "options": results,
            "analysis_text": analysis_text,
        }

    async def _get_train_info_with_retry(
        self,
        departure: str,
        destination: str,
        date: str,
        retries: int = 3,
    ) -> Dict[str, Any]:
        last_error: Optional[Dict[str, Any]] = None

        for attempt in range(1, retries + 1):
            try:
                r = await self.mcp_client.query_12306_trains(departure, destination, date)

                if not r.get("success"):
                    last_error = {
                        "type": "api_error",
                        "message": r.get("error"),
                        "http_status": (r.get("meta") or {}).get("status"),
                        "raw": r.get("raw"),
                        "meta": r.get("meta"),
                    }
                    await asyncio.sleep(0.4 * attempt)
                    continue

                return {
                    "ok": True,
                    "source": "12306-mcp",
                    "raw": r.get("data"),
                    "summary": r.get("summary"),
                    "meta": r.get("meta"),
                }

            except Exception as e:
                last_error = {"type": "exception", "message": str(e)}
                await asyncio.sleep(0.4 * attempt)

        return {
            "ok": False,
            "source": "12306-mcp",
            "error": last_error or {"type": "unknown", "message": "train query failed"},
        }

    async def _get_flight_info(self, departure: str, destination: str, date: str) -> Dict[str, Any]:
        dep_code = to_iata_city_code(departure) or departure
        arr_code = to_iata_city_code(destination) or destination

        if not (isinstance(dep_code, str) and len(dep_code) == 3):
            return {
                "ok": False,
                "source": "variflight-mcp",
                "error": {"type": "invalid_input", "message": f"无法解析出发城市IATA码：{departure}"},
            }

        if not (isinstance(arr_code, str) and len(arr_code) == 3):
            return {
                "ok": False,
                "source": "variflight-mcp",
                "error": {"type": "invalid_input", "message": f"无法解析目的地IATA码：{destination}"},
            }

        r = await self.variflight_client.search_flight_itineraries(dep_code, arr_code, date)

        if not r.get("success"):
            return {
                "ok": False,
                "source": "variflight-mcp",
                "error": {
                    "type": "api_error",
                    "message": r.get("error"),
                    "http_status": (r.get("meta") or {}).get("status"),
                    "raw": r.get("raw"),
                    "meta": r.get("meta"),
                },
                "query": {"depCityCode": dep_code, "arrCityCode": arr_code, "depDate": date},
            }

        return {
            "ok": True,
            "source": "variflight-mcp",
            "raw": r.get("data"),
            "meta": r.get("meta"),
            "query": {"depCityCode": dep_code, "arrCityCode": arr_code, "depDate": date},
        }

    def _no_data_or_error_summary(
        self,
        departure: str,
        destination: str,
        date: str,
        results: Dict[str, Any],
        profile_json: str,
    ) -> Optional[str]:
        """
        若 train/flight 都没有可用 raw 数据，则返回固定文本（不调用LLM，防止常识补全）。
        返回 None 表示至少有一种方式有数据，可以调用 LLM。
        """
        train = results.get("train") if isinstance(results.get("train"), dict) else {}
        flight = results.get("flight") if isinstance(results.get("flight"), dict) else {}

        train_ok = _is_nonempty_list(train.get("raw")) if isinstance(train, dict) else False
        flight_ok = _is_nonempty_list(flight.get("raw")) if isinstance(flight, dict) else False

        if train_ok or flight_ok:
            return None

        parts: List[str] = []
        parts.append("【数据不足】暂时没有拿到可用的火车/航班列表，因此无法基于真实数据做比价与推荐。")
        parts.append(f"出发地：{departure}；目的地：{destination}；出发日期：{date}")

        if isinstance(train, dict) and train.get("error"):
            parts.append(f"火车查询：失败（{train.get('error')}）")
        else:
            parts.append("火车查询：无返回数据（可能是接口暂时不可用或被限流）")

        if isinstance(flight, dict) and flight.get("error"):
            parts.append(f"航班查询：失败/无方案（{flight.get('error')}）")
        else:
            parts.append("航班查询：无返回数据")

        parts.append("【下一步建议】")
        parts.append("1) 我可以立刻为你重试一次查询（火车 502/超时通常是暂时性的）。")
        parts.append("2) 如果航班持续无数据，可能需要你确认出发/到达城市是否匹配航班数据源，或换一天出发日期再试。")
        parts.append("3) 若你希望我只查火车或只查航班，也可以告诉我。")

        p = _safe_json_loads(profile_json)
        if _is_valid_yyyy_mm_dd(p.get("return_date")):
            parts.append(f"补充：你还提供了返程日期 {p.get('return_date')}，需要我把回程交通也一起比价吗？")

        return "\n".join(parts)

    async def _analyze_transport_options_text(
        self,
        transport_data: Dict[str, Any],
        departure: str,
        destination: str,
        date: str,
        profile_json: str = "",
    ) -> str:
        # 控制 raw 长度，避免 token 爆炸
        compact: Dict[str, Any] = {}
        for k, v in transport_data.items():
            if not isinstance(v, dict):
                compact[k] = v
                continue
            vv = dict(v)
            raw = vv.get("raw")
            if isinstance(raw, list):
                vv["raw"] = raw[:10]
            compact[k] = vv

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "你是交通比价助手。你会收到交通查询数据（火车/航班）与用户画像profile。\n"
                    "严格规则（必须遵守）：\n"
                    "- 只能基于“交通数据”中给出的内容做结论；禁止用常识/经验补全价格、时长、车次/航班号。\n"
                    "- 禁止出现“通常/一般/大概X小时/经验上”等推断语句。\n"
                    "- 如果某方式数据缺失或只有 error，请明确写“数据缺失/查询失败”，并给下一步建议。\n"
                    "- 输出只要纯文本，不要JSON，不要代码块。\n\n"
                    "输出结构必须包含：\n"
                    "【结论】1-2句话：总体建议（仅基于数据）。\n"
                    "【火车建议】如有数据：给出“最快/最省/综合”各1条（引用数据字段；缺字段就说明缺失）。\n"
                    "【飞机建议】如有数据：给出“最快/最省/综合”各1条（引用数据字段；缺字段就说明缺失）。\n"
                    "【对比建议】仅基于数据的对比点：价格区间、出发到达时间段、是否直达/中转等（数据没有就不要写）。\n"
                    "【下一步确认】最多2个问题，用于推进下一步（例如：是否固定出发时段/是否只看直达/是否只看高铁）。",
                ),
                (
                    "human",
                    "出发地：{departure}\n"
                    "目的地：{destination}\n"
                    "出发日期：{date}\n"
                    "用户画像profile(JSON)：{profile_json}\n"
                    "交通数据(JSON)：{compact}\n",
                ),
            ]
        )

        chain = prompt | self.llm | StrOutputParser()
        try:
            text = await chain.ainvoke(
                {
                    "departure": departure,
                    "destination": destination,
                    "date": date,
                    "profile_json": _compact_profile(profile_json),
                    "compact": json.dumps(compact, ensure_ascii=False),
                }
            )
            text = (text or "").strip()
            return text if text else "已获取到交通数据，但模型未返回分析文本。"
        except Exception as e:
            return f"分析失败：{e}"


# 单例执行器（减少重复初始化）
_EXECUTOR = TransportExecutor()


# -----------------------------
# 去/返程汇总文本（纯本地拼接，避免LLM乱写结构）
# -----------------------------

def _merge_two_legs_text(
    outbound_text: str,
    return_text: Optional[str],
    outbound: Tuple[str, str, str],
    inbound: Optional[Tuple[str, str, str]],
) -> str:
    """
    把去程/返程两段分析文本汇总成一段可读文本，不“创造”任何数据。
    这里不尝试重写推荐，只做分段。
    """
    dep, dst, d1 = outbound
    parts = []
    parts.append(f"【去程】{dep} → {dst}（{d1}）")
    parts.append(outbound_text.strip() if outbound_text else "（去程暂无可用分析文本）")

    if return_text is not None and inbound is not None:
        rdep, rdst, d2 = inbound
        parts.append("")
        parts.append(f"【返程】{rdep} → {rdst}（{d2}）")
        parts.append(return_text.strip() if return_text else "（返程暂无可用分析文本）")

    return "\n".join(parts).strip()


# -----------------------------
# Tool
# -----------------------------

@tool
def compare_transport(
    profile_json: str,
    trip_type: str = "roundtrip",   # outbound | inbound | roundtrip
    enable_debug: bool = True
) -> str:
    """
    交通比价工具（执行型）：
    - 输入：profile_json（UserProfile.to_dict() 的 JSON 字符串）
    - trip_type:
        - "outbound": 仅查去程（depart_city -> destination, departure_date）
        - "inbound": 仅查返程（destination -> depart_city, return_date）
        - "roundtrip": 去程必查；返程若 return_date 合法则追加查询
    - 输出：
        - data.text：可直接回复用户的纯文本（含去/返程视 trip_type）
        - data.outbound / data.inbound：结构化结果（options/debug等）
    """
    trip_type = (trip_type or "").strip().lower()
    if trip_type not in ("outbound", "inbound", "roundtrip"):
        return tool_return({
            "ok": False,
            "source": "transport-exec",
            "error": f"trip_type 不合法：{trip_type}（应为 outbound / inbound / roundtrip）",
        })

    p = parse_transport_args_from_profile(profile_json)

    depart_city = _normalize_city(p.get("departure"))
    destination = _normalize_city(p.get("destination"))
    dep_date = (p.get("departure_date") or "").strip() if isinstance(p.get("departure_date"), str) else ""
    ret_date = (p.get("return_date") or "").strip() if isinstance(p.get("return_date"), str) else ""

    # ---- 根据 trip_type 做硬约束校验 ----
    def _missing_err(fields: List[str]) -> str:
        return "交通比价缺少/不合法信息：" + "、".join(fields) + "。"

    if trip_type == "outbound":
        missing = []
        if not depart_city:
            missing.append("出发城市")
        if not destination:
            missing.append("目的地")
        if not dep_date:
            missing.append("出发日期")
        elif not _is_valid_yyyy_mm_dd(dep_date):
            missing.append("出发日期不合法")
        if missing:
            return tool_return({"ok": False, "source": "transport-exec", "error": _missing_err(missing)})

    elif trip_type == "inbound":
        # 返程：起终点对换 + 用 return_date
        missing = []
        if not depart_city:
            missing.append("出发城市（用于返程到达）")
        if not destination:
            missing.append("目的地（用于返程出发）")
        if not ret_date:
            missing.append("返程日期")
        elif not _is_valid_yyyy_mm_dd(ret_date):
            missing.append("返程日期不合法")
        if missing:
            return tool_return({"ok": False, "source": "transport-exec", "error": _missing_err(missing)})

    else:  # roundtrip
        # 去程必需
        missing = []
        if not depart_city:
            missing.append("出发城市")
        if not destination:
            missing.append("目的地")
        if not dep_date:
            missing.append("出发日期")
        elif not _is_valid_yyyy_mm_dd(dep_date):
            missing.append("出发日期不合法")
        if missing:
            return tool_return({"ok": False, "source": "transport-exec", "error": _missing_err(missing)})

    # ---- 执行查询 ----
    dbg_out = TransportDebug() if enable_debug and trip_type in ("outbound", "roundtrip") else None
    dbg_in = TransportDebug() if enable_debug and trip_type in ("inbound", "roundtrip") else None

    try:
        outbound_plan = None
        inbound_plan = None
        outbound_data = None
        inbound_data = None
        notes: List[str] = []

        # 去程
        if trip_type in ("outbound", "roundtrip"):
            outbound_plan = _run_coro_sync(
                _EXECUTOR.get_transport_plan(
                    departure=depart_city,
                    destination=destination,
                    date=dep_date,
                    transport_types=["train", "flight"],
                    profile_json=profile_json,
                    debug=dbg_out,
                )
            )
            outbound_data = {
                "text": outbound_plan.get("analysis_text", ""),
                "departure": depart_city,
                "destination": destination,
                "departure_date": dep_date,
                "options": outbound_plan.get("options"),
            }
            if enable_debug and dbg_out is not None:
                outbound_data["debug"] = {
                    "train_ok": dbg_out.train_ok,
                    "flight_ok": dbg_out.flight_ok,
                    "train_error": dbg_out.train_error,
                    "flight_error": dbg_out.flight_error,
                    "train_raw_len": dbg_out.train_raw_len,
                    "flight_raw_len": dbg_out.flight_raw_len,
                    "flight_query": dbg_out.flight_query,
                }

        # 返程
        if trip_type == "inbound":
            inbound_plan = _run_coro_sync(
                _EXECUTOR.get_transport_plan(
                    departure=destination,
                    destination=depart_city,
                    date=ret_date,
                    transport_types=["train", "flight"],
                    profile_json=profile_json,
                    debug=dbg_in,
                )
            )
            inbound_data = {
                "text": inbound_plan.get("analysis_text", ""),
                "departure": destination,
                "destination": depart_city,
                "departure_date": ret_date,
                "options": inbound_plan.get("options"),
            }
            if enable_debug and dbg_in is not None:
                inbound_data["debug"] = {
                    "train_ok": dbg_in.train_ok,
                    "flight_ok": dbg_in.flight_ok,
                    "train_error": dbg_in.train_error,
                    "flight_error": dbg_in.flight_error,
                    "train_raw_len": dbg_in.train_raw_len,
                    "flight_raw_len": dbg_in.flight_raw_len,
                    "flight_query": dbg_in.flight_query,
                }

        elif trip_type == "roundtrip":
            if _is_valid_yyyy_mm_dd(ret_date):
                inbound_plan = _run_coro_sync(
                    _EXECUTOR.get_transport_plan(
                        departure=destination,
                        destination=depart_city,
                        date=ret_date,
                        transport_types=["train", "flight"],
                        profile_json=profile_json,
                        debug=dbg_in,
                    )
                )
                inbound_data = {
                    "text": inbound_plan.get("analysis_text", ""),
                    "departure": destination,
                    "destination": depart_city,
                    "departure_date": ret_date,
                    "options": inbound_plan.get("options"),
                }
                if enable_debug and dbg_in is not None:
                    inbound_data["debug"] = {
                        "train_ok": dbg_in.train_ok,
                        "flight_ok": dbg_in.flight_ok,
                        "train_error": dbg_in.train_error,
                        "flight_error": dbg_in.flight_error,
                        "train_raw_len": dbg_in.train_raw_len,
                        "flight_raw_len": dbg_in.flight_raw_len,
                        "flight_query": dbg_in.flight_query,
                    }
            else:
                if ret_date:
                    notes.append("我看到你给了返程日期，但它目前不太像一个明确日期，所以这次先只查了去程；如果你愿意，告诉我返程那天我也可以一起比一下。")
                else:
                    notes.append("如果你也想把返程一起对比，把返程那天告诉我，我可以把回程火车/航班也一起查出来。")

        # ---- 汇总文本 ----
        if trip_type == "outbound":
            merged_text = _merge_two_legs_text(
                outbound_text=(outbound_data or {}).get("text", ""),
                return_text=None,
                outbound=(depart_city, destination, dep_date),
                inbound=None,
            )
        elif trip_type == "inbound":
            merged_text = _merge_two_legs_text(
                outbound_text=(inbound_data or {}).get("text", ""),
                return_text=None,
                outbound=(destination, depart_city, ret_date),
                inbound=None,
            )
        else:
            merged_text = _merge_two_legs_text(
                outbound_text=(outbound_data or {}).get("text", ""),
                return_text=(inbound_data or {}).get("text", "") if inbound_data else None,
                outbound=(depart_city, destination, dep_date),
                inbound=((destination, depart_city, ret_date) if inbound_data else None),
            )

        if notes:
            merged_text = merged_text + "\n\n" + "\n".join(notes)

        return tool_return({
            "ok": True,
            "source": "transport-exec",
            "data": {
                "text": merged_text,
                "trip_type": trip_type,
                "outbound": outbound_data,
                "inbound": inbound_data,
                "has_inbound": bool(inbound_data),
            },
        })

    except Exception as e:
        return tool_return({
            "ok": False,
            "source": "transport-exec",
            "error": f"交通比价工具执行失败：{str(e)}",
        })

