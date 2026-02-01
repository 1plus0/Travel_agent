from fastapi import APIRouter
from app.core.config import settings

# 创建通用路由实例
router = APIRouter(
    tags=["通用接口"]
)

@router.get("/")
async def root():
    """根路径接口"""
    return {"message": f"欢迎来到 {settings.PROJECT_NAME} 后端接口"}
