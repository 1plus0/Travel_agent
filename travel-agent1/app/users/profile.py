from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any

@dataclass
class UserProfile:
    depart_city: Optional[str] = None
    month: Optional[str] = None          # "2月" / "2026-02" 都行
    departure_date: Optional[str] = None
    return_date: Optional[str] = None
    days: Optional[int] = None
    budget_cny: Optional[int] = None
    preferences: Optional[str] = None    # "美食 人文" 这种即可
    people: Optional[int] = None
    destination: Optional[str] = None    # 用户明确提到的目的地（比如“大阪”）

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # 去掉 None，输出更干净
        return {k: v for k, v in d.items() if v is not None}

def merge_profile(p: UserProfile, update: Dict[str, Any]) -> UserProfile:
    # 只更新非空字段
    for k, v in update.items():
        if v is None:
            continue
        if hasattr(p, k):
            setattr(p, k, v)
    return p
