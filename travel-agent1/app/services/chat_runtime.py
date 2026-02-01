# app/services/chat_runtime.py
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Tuple, Any, List

from langchain.agents import create_agent
from langchain.messages import SystemMessage
from langchain_core.messages import BaseMessage, HumanMessage

from app.agents.base import get_model
from app.agents.hotel_agent import recommend_hotels_nearby
from app.agents.destination_agent import recommend_and_plan_trip
from app.agents.transport_agent import compare_transport

from app.tools.weather import get_15d_weather
from app.tools.search_spots import search_hot_scenic_spots

from app.users.profile import UserProfile, merge_profile
from app.agents.profile_extractor import extract_profile_update


def load_system_prompt(name: str = "system_prompt.txt") -> str:
    prompt_path = Path(__file__).parent.parent / "prompts" / name
    return prompt_path.read_text(encoding="utf-8")


SYSTEM_PROMPT = load_system_prompt("system_prompt.txt")

# 全局复用（避免每个请求重建一次模型/agent）
MAIN_LLM = get_model(temperature=0.3)
EXTRACTOR_LLM = get_model(temperature=0)

AGENT = create_agent(
    model=MAIN_LLM,
    tools=[
        compare_transport,
        recommend_and_plan_trip,
        recommend_hotels_nearby,
        search_hot_scenic_spots,
        get_15d_weather,
    ],
    system_prompt=SystemMessage(content=SYSTEM_PROMPT),
)


def run_one_turn(
    profile: UserProfile,
    history: List[BaseMessage],
    user_text: str,
) -> Tuple[str, UserProfile, List[BaseMessage]]:
    """
    单轮对话：
    1) 抽取并更新 profile
    2) 注入 today + profile（system message）
    3) agent.invoke
    4) 返回 assistant_text + 更新后的 profile + 更新后的 history

    说明：history 必须保存完整 messages（包含 tool messages），否则多工具串联会断。
    """
    # 1) 更新 profile
    update = extract_profile_update(EXTRACTOR_LLM, user_text, today=date.today())
    profile = merge_profile(profile, update)

    today_msg = SystemMessage(content=f"今天的日期是：{date.today()}（请你在回答天气/行程时以此为准）")
    profile_msg = SystemMessage(content=f"当前已知用户条件为：{profile.to_dict()}")

    # 2) 组装 messages
    turn_messages = history + [today_msg, profile_msg, HumanMessage(content=user_text)]

    # 3) 调用 agent
    r = AGENT.invoke({"messages": turn_messages})
    messages = r.get("messages", None)
    if not messages:
        # 兜底：不同版本返回可能只给 output
        assistant_text = r.get("output", "")
        new_history = history + [HumanMessage(content=user_text), SystemMessage(content=assistant_text)]
        return assistant_text, profile, new_history

    assistant_msg = messages[-1]
    assistant_text = getattr(assistant_msg, "content", str(assistant_msg))

    # 4) 更新 history：保存完整 messages（含 tool messages）
    new_history = messages
    return assistant_text, profile, new_history
