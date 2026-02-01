from fastapi import APIRouter
from app.agents.base import get_model

# 创建路由实例，可以设置前缀和标签
router = APIRouter(
    prefix="/test",  # 所有路由都会自动添加 /test 前缀
    tags=["测试接口"]  # 在 Swagger 文档中分组显示
)

@router.get("/ai")
async def test_ai():
    """测试 AI 模型连接"""
    llm = get_model()
    try:
        response = llm.invoke("你好，请用一句话证明你已经联网了。")
        return {"status": "success", "ai_response": response.content}
    except Exception as e:
        return {"status": "error", "message": str(e)}
