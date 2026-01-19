from app.prompts.templates import TEMPLATES


def render_prompt(name: str, **kwargs):
    """
    LangChain 化的渲染器：取出 ChatPromptTemplate 并调用 .format_messages
    - ChatPromptTemplate 会校验所需变量，缺失时抛出 ValueError。
    - 返回的是 LangChain Messages，对接下游 Runnable/模型更自然。
    """
    tpl = TEMPLATES.get(name)
    if not tpl:
        raise ValueError(f"unknown prompt {name}")

    # ChatPromptTemplate 自带格式化与校验
    return tpl.format_messages(**kwargs)