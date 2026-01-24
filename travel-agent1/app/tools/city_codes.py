from __future__ import annotations

from typing import Optional

from app.data.city_code_map import CITY_CODE_MAP


ALIASES = {
    "北京市": "北京",
    "上海市": "上海",
    "广州市": "广州",
    "深圳市": "深圳",
    "西安市": "西安",
    "成都市": "成都",
    "重庆市": "重庆",
}


def to_iata_city_code(name_or_code: str) -> Optional[str]:
    """
    输入：中文城市名（北京）或 IATA 城市三字码（BJS）
    输出：IATA 城市三字码（大写）
    """
    s = (name_or_code or "").strip()
    if not s:
        return None

    # 已是三字码
    if len(s) == 3 and s.isalpha():
        return s.upper()

    s = ALIASES.get(s, s)
    code = CITY_CODE_MAP.get(s)
    return code.upper() if isinstance(code, str) and code else None