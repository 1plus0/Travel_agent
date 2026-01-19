from pydantic import BaseModel
from typing import Optional

class TravelRequest(BaseModel):
    budget: str          # 预算范围（如 "15000元以上（奢华型）"）
    people: str          # 出行人数（如 "2人（情侣/好友）"）
    days: str            # 出行天数（如 "1-2天（周末游）"）
    interest: str        # 兴趣类型（如 "自然风光（山水湖泊）"）
    special: Optional[str] = None  # 特殊需求（可选）