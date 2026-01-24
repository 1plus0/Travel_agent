from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from app.agents.transport_agent import TransportAgent

router = APIRouter(
    prefix="/transport",
    tags=["交通比价"]
)

class TransportQuery(BaseModel):
    departure: str
    destination: str
    date: str  # YYYY-MM-DD
    transport_types: Optional[List[str]] = ['train', 'flight']

class TransportResponse(BaseModel):
    status: str
    data: dict

@router.post("/compare", response_model=TransportResponse)
async def compare_transport(query: TransportQuery):
    """交通方式比价接口"""
    try:
        # 验证日期格式
        datetime.strptime(query.date, '%Y-%m-%d')
        
        agent = TransportAgent()
        result = await agent.get_transport_plan(
            departure=query.departure,
            destination=query.destination,
            date=query.date,
            transport_types=query.transport_types
        )
        
        return TransportResponse(status="success", data=result)
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"日期格式错误: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")
