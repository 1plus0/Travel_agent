from langchain_openai import ChatOpenAI
from app.core.config import settings

def get_model(temperature=0.7):
    """
    初始化 DeepSeek 模型
    temperature: 0.0 最严谨(适合比价)，1.0 最发散(适合推荐)
    """
    return ChatOpenAI(
        model="deepseek-chat",
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        temperature=temperature
    )