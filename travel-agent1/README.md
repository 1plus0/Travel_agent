# 1. 创建新环境，建议使用 Python 3.10 或 3.11，版本稳定且兼容性好
conda create -n travel_agent python=3.10 -y

# 2. 激活环境
conda activate travel_agent

# 3. 检查当前环境路径（确保你在刚创建的环境里）
python --version


pip install fastapi uvicorn python-dotenv pydantic-settings langchain>=0.1.0 langchain-openai langchain-community tavily-python


uvicorn app.main:app --reload
