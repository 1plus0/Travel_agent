# 1. 创建新环境，建议使用 Python 3.10 或 3.11，版本稳定且兼容性好
conda create -n travel_agent python=3.10 -y

# 2. 激活环境
conda activate travel_agent

# 3. 检查当前环境路径（确保你在刚创建的环境里）
python --version

# 4. 下载以下依赖
pip install fastapi uvicorn python-dotenv pydantic-settings langchain>=0.1.0 langchain-openai langchain-community tavily-python

# 5. 创建.env文件，填写 DeepSeek 密钥等
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
TAVILY_API_KEY=tvly-xxxxxxx

# 6.启动
uvicorn app.main:app --reload


