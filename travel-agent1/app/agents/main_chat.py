from langchain.agents import create_agent
from langchain.messages import SystemMessage
from pathlib import Path
import sys
import os

from app.agents.base import get_model
from app.agents.hotel_agent import recommend_hotels_nearby
from app.agents.destination_agent import recommend_and_plan_trip
from app.agents.transport_agent import compare_transport

from app.tools.weather import get_15d_weather
from app.tools.search_spots import search_hot_scenic_spots
from app.users.profile import UserProfile, merge_profile
from app.agents.profile_extractor import extract_profile_update


from datetime import date

def load_system_prompt(name: str = "system_prompt.txt") -> str:
    prompt_path = Path(__file__).parent.parent /"app"/ "prompts" / name
    return prompt_path.read_text(encoding="utf-8")

today_msg = {
    "role": "system",
    "content": f"今天的日期是：{date.today()}（请你在回答天气/行程时以此为准）"
}

extractor_llm = get_model(temperature=0)

SYSTEM_PROMPT = load_system_prompt("system_prompt.txt")


def build_agent():
    model = get_model(temperature=0.3)
    agent = create_agent(
        model=model,
        tools=[
        compare_transport,
        recommend_and_plan_trip,
        recommend_hotels_nearby,
        search_hot_scenic_spots,
        get_15d_weather, 
        ],
        system_prompt=SystemMessage(content=SYSTEM_PROMPT),
    )
    return agent, model

if __name__ == "__main__":
    agent, model = build_agent()

    profile = UserProfile()
    messages = []

    while True:
        user = input("用户：").strip()
        if user.lower() in ("exit", "quit"):
            break

        # 1) 先抽取条件，更新 profile（C 的核心）
        update = extract_profile_update(extractor_llm, user, today=date.today())
        profile = merge_profile(profile, update)

        # 2) 把“当前 profile”注入对话（作为 system message）
        profile_msg = {
            "role": "system",
            "content": f"当前已知用户条件（profile）为：{profile.to_dict()}"
        }

        # 3) 组装 messages：保留历史 + 当前 profile + 用户输入
        #    这里的做法：每轮都临时插入 profile_msg（不必永久写进历史）
        turn_messages = messages + [today_msg, profile_msg, {"role": "user", "content": user}]

        r = agent.invoke({"messages": turn_messages})
        assistant = r["messages"][-1]

        print("助手：", assistant.content)

        # 4) 存历史（只存 user 和 assistant，不存 profile_msg）
        messages.append({"role": "user", "content": user})
        messages.append({"role": "assistant", "content": assistant.content})
