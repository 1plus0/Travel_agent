from __future__ import annotations

import re
from typing import Any, Dict, Optional

_DURATION_RE = re.compile(r"(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?", re.IGNORECASE)


def _duration_to_minutes(s: Optional[str]) -> Optional[int]:
    if not s:
        return None

    m = _DURATION_RE.search(s.strip().replace(" ", ""))
    if not m:
        return None

    h = int(m.group(1)) if m.group(1) else 0
    mins = int(m.group(2)) if m.group(2) else 0
    if h == 0 and mins == 0:
        return None

    return h * 60 + mins


def _parse_block(text: str, title: str) -> Optional[Dict[str, Any]]:
    idx = text.find(title)
    if idx < 0:
        return None
    seg = text[idx : idx + 450]

    fno = None
    dep_time = None
    arr_time = None
    duration_text = None
    price = None

    m = re.search(r"航班号[:：]\s*([A-Z0-9]+)", seg)
    if m:
        fno = m.group(1)

    m = re.search(r"起飞时间[:：]\s*([0-9:\- ]{10,19})", seg)
    if m:
        dep_time = m.group(1).strip()

    m = re.search(r"到达时间[:：]\s*([0-9:\- ]{10,19})", seg)
    if m:
        arr_time = m.group(1).strip()

    m = re.search(r"耗时[:：]\s*([0-9hHmM ]+)", seg)
    if m:
        duration_text = m.group(1).strip().replace(" ", "")

    m = re.search(r"价格[:：]\s*(\d+)\s*元", seg)
    if m:
        price = int(m.group(1))

    if not fno:
        return None

    return {
        "flight_no": fno,
        "dep_time": dep_time,
        "arr_time": arr_time,
        "duration_text": duration_text,
        "duration_minutes": _duration_to_minutes(duration_text),
        "price": price,
    }


def parse_variflight_summary(raw_text: Any) -> Dict[str, Any]:
    text = raw_text if isinstance(raw_text, str) else str(raw_text)

    count = None
    min_price = None
    min_duration_text = None
    min_duration_minutes = None

    m = re.search(r"查询到了\s*(\d+)\s*条", text)
    if m:
        count = int(m.group(1))

    m = re.search(r"最低价[:：]\s*(\d+)\s*元", text)
    if m:
        min_price = int(m.group(1))

    m = re.search(r"最短耗时[:：]\s*([0-9hHmM ]+)", text)
    if m:
        min_duration_text = m.group(1).strip().replace(" ", "")
        min_duration_minutes = _duration_to_minutes(min_duration_text)

    return {
        "count": count,
        "min_price": min_price,
        "min_duration_text": min_duration_text,
        "min_duration_minutes": min_duration_minutes,
        "cheapest": _parse_block(text, "最低价航班为"),
        "fastest": _parse_block(text, "最短耗时航班为"),
    }