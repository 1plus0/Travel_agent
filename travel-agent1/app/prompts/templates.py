from langchain_core.prompts import ChatPromptTemplate

# 使用 LangChain 原生 ChatPromptTemplate 管理提示词：
# - 提供变量占位符校验，减少运行时报错。
# - 输出为 messages 对象，可直接与 Runnable 链接到模型。
TEMPLATES = {
    "travel_plan": ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "你是智能出行规划助理，输出简洁可执行的行程方案。",
            ),
            (
                "user",
                "出行地：{city}\n"
                "天数：{days} 天\n"
                "偏好：{preferences}\n"
                "预算：{budget}\n"
                "请输出分日程表，附交通/餐饮/住宿建议。",
            ),
        ]
    )
}