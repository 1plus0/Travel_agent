from app.agents.base import get_model
from app.prompts.renderer import render_prompt
from app.prompts.templates import TEMPLATES


def run_prompt(name: str, temperature=0.6, **kwargs):
    """
    LangChain 化执行流程：
    1) 从模板仓库取出 ChatPromptTemplate，并格式化为 messages。
    2) 获取 LLM（ChatOpenAI），可调整 temperature 控制创造性。
    3) 通过简单链式组合（prompt -> llm）执行，返回文本结果。
    """
    if name not in TEMPLATES:
        raise ValueError(f"unknown prompt {name}")

    prompt = TEMPLATES[name]
    llm = get_model(temperature=temperature)

    # LangChain 的链式组合：prompt | llm
    chain = prompt | llm

    # chain.invoke 支持 dict 入参，内部会完成 messages 渲染与模型调用
    resp = chain.invoke(kwargs)
    return resp.content