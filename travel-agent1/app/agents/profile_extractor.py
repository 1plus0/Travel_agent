import json
import re
from typing import Dict, Any, Optional
from datetime import date

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser


EXTRACT_PROMPT = """
你是一个信息抽取器。请从用户输入中抽取旅游条件。

你必须输出“严格 JSON”，不要输出任何其它文字、解释、标点、Markdown。
只允许输出一个 JSON 对象。

今天日期（用于推断相对时间）：{today}

日期字段规则：
- departure_date 和 return_date：
  1) 如果用户明确给了具体日期，请输出 YYYY-MM-DD
  2) 如果用户给的是相对时间（如“两周后/下周五/明天/后天/周末/今年1月30号”），请你基于“今天日期”换算成一个确定的 YYYY-MM-DD。
  3）如果用户没有给出年份，默认为当下的年份
  4) 如果仍然无法确定（例如用户没有任何可落地线索），可以输出 null，并尽量把月份信息写入 month（如“2月”或“2026-02”）。

JSON 必须包含以下键（没提到就填 null）：
- depart_city
- month
- departure_date
- return_date
- days
- budget_cny
- preferences
- people
- destination

用户输入：{text}
"""

REQUIRED_KEYS = [
    "depart_city", "month", "departure_date", "return_date",
    "days", "budget_cny", "preferences", "people", "destination"
]


def _empty_payload() -> Dict[str, Any]:
    return {k: None for k in REQUIRED_KEYS}


def _safe_json_from_text(s: str) -> Dict[str, Any]:
    """
    尝试从字符串中解析 JSON。
    兼容模型偶尔输出前后带文字的情况：只截取第一个 {...}。
    """
    if not s:
        return _empty_payload()

    s = s.strip()

    # 1) 直接尝试
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # 2) 截取第一个 JSON 对象
    l = s.find("{")
    r = s.rfind("}")
    if l != -1 and r != -1 and r > l:
        candidate = s[l:r + 1]
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    return _empty_payload()


def _coerce_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        vv = v.strip()
        if vv.isdigit():
            return int(vv)
    return None


def _looks_like_iso_date(s: str) -> bool:
    return bool(re.fullmatch(r"20\d{2}-\d{2}-\d{2}", s.strip()))


def validate_dates_against_today(update: Dict[str, Any], user_text: str, today: date) -> Dict[str, Any]:
    """
    目标：不替 AI“完整推理”日期，但做强约束校验，避免明显错误污染 profile。
    - 若用户出现“今年”，强制年份= today.year
    - 若用户未给年份但 AI 给了“离谱的过去日期”（>370天前），置空
    - 若不是合法 YYYY-MM-DD / 不可构造 date，置空
    """
    def _fix_one(field: str):
        raw = update.get(field)
        if raw is None:
            return
        if not isinstance(raw, str):
            update[field] = None
            return

        raw = raw.strip()
        if not _looks_like_iso_date(raw):
            update[field] = None
            return

        y, m, d = map(int, raw.split("-"))
        try:
            dd = date(y, m, d)
        except ValueError:
            update[field] = None
            return

        # 1) 用户明确说“今年”
        if "今年" in user_text:
            if y != today.year:
                update[field] = f"{today.year:04d}-{m:02d}-{d:02d}"
                return

        # 2) 用户没写年份时，拦截“明显离谱的过去日期”
        #    （例如今天是2026-01-28，AI却给2025-01-30）
        has_explicit_year = bool(re.search(r"\b20\d{2}\b", user_text))
        if not has_explicit_year:
            if (today - dd).days > 370:
                update[field] = None

    _fix_one("departure_date")
    _fix_one("return_date")
    return update


def normalize_month_from_dates(update: Dict[str, Any]) -> Dict[str, Any]:
    """
    如果 month 缺失但 departure_date 有，则补齐 month=YYYY-MM。
    """
    if not update.get("month") and isinstance(update.get("departure_date"), str) and _looks_like_iso_date(update["departure_date"]):
        update["month"] = update["departure_date"][:7]
    return update


def extract_profile_update(llm, user_text: str, today: Optional[date] = None) -> Dict[str, Any]:
    """
    从用户输入抽取 profile 更新：
    - 把 today 显式传入 LLM，让其自行将相对时间换算为绝对日期
    - 本地做强校验，避免年份明显错误污染 profile
    """
    if today is None:
        today = date.today()

    prompt = ChatPromptTemplate.from_template(EXTRACT_PROMPT)
    chain = prompt | llm | StrOutputParser()

    s = chain.invoke({"text": user_text, "today": today.strftime("%Y-%m-%d")}).strip()
    data = _safe_json_from_text(s)

    out = _empty_payload()
    if isinstance(data, dict):
        for k in REQUIRED_KEYS:
            out[k] = data.get(k, None)

    # 轻量数值字段清洗
    out["days"] = _coerce_int(out.get("days"))
    out["budget_cny"] = _coerce_int(out.get("budget_cny"))
    out["people"] = _coerce_int(out.get("people"))

    # 日期强校验（防 2025/2026 之类的明显偏差）
    out = validate_dates_against_today(out, user_text=user_text, today=today)

    # month 补齐
    out = normalize_month_from_dates(out)

    # 保证 keys 齐全
    final_out = _empty_payload()
    final_out.update({k: out.get(k, None) for k in REQUIRED_KEYS})
    return final_out
