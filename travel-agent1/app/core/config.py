from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # 项目信息
    PROJECT_NAME: str = "AI 智能出行管家"
    VERSION: str = "1.0.0"
    
    # API 密钥（会自动从 .env 读取同名变量）
    DEEPSEEK_API_KEY: str
    DEEPSEEK_BASE_URL: str
    TAVILY_API_KEY: str
    MCP_12306_REMOTE_URL: str
    MCP_VARIFLIGHT_REMOTE_URL: str


    class Config:
        env_file = ".env"

# 实例化，方便全局调用
settings = Settings()