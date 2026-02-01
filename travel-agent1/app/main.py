from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html # 导入手动构建文档的方法
from app.core.config import settings
from fastapi.middleware.cors import CORSMiddleware
from app.routers import test, common, chat  # 添加 transport 导入
from app.tools.mcp_tools import MCPTransportClient
from app.tools.variflight_mcp_tools import VariflightMCPClient  # <-- 新增

# 1. 初始化时禁用默认的 docs_url
app = FastAPI(
    title=settings.PROJECT_NAME, 
    version=settings.VERSION,
    docs_url=None,  # 禁用默认地址
    redoc_url=None  # 同时也禁用 redoc
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # 允许所有域名访问（开发阶段比较方便）
    allow_credentials=True,
    allow_methods=["*"],      # 允许所有请求方法 (GET, POST 等)
    allow_headers=["*"],      # 允许所有请求头
)

# 2. 手动创建 Swagger 文档路由，使用国内镜像
@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        # 换用 BootCDN 提供的 5.x 版本资源
        swagger_js_url="https://cdn.bootcdn.net/ajax/libs/swagger-ui/5.9.0/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.bootcdn.net/ajax/libs/swagger-ui/5.9.0/swagger-ui.css",
    )

# 3. 注册路由模块
app.include_router(common.router)  # 通用接口，如根路径 /
app.include_router(test.router)    # 测试接口，如 /test/ai
app.include_router(chat.router)

    # @app.get("/debug/mcp/12306/tools")
    # async def debug_list_12306_tools():
    #     client = MCPTransportClient()
    #     return await client.list_tools()

    # @app.get("/debug/mcp/variflight/tools")
    # async def debug_list_variflight_tools():
    #     client = VariflightMCPClient()
    #     return await client.list_tools()


