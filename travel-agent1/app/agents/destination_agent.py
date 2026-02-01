import json
from typing import Any, Dict, List

from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# 1. 导入你写的高德景点搜索工具（根据实际项目路径调整，确保能导入）
from app.tools.search_spots import search_hot_scenic_spots  # 替换为你实际的工具文件路径
from app.tools.utils import tool_return
from app.core.config import settings
from app.agents.base import get_model


def _safe_json(text: str) -> Dict[str, Any]:
    """profile_json解析失败时兜底"""
    try:
        return json.loads(text) if text else {}
    except Exception:
        return {}


def _compact_profile(profile_json: str, max_chars: int = 2000) -> str:
    """
    把profile做轻度裁剪，防止prompt过长。
    你后面可以改成“只取关键字段”。
    """
    s = (profile_json or "").strip()
    if not s:
        return "{}"
    if len(s) > max_chars:
        return s[:max_chars] + "…(truncated)"
    return s


# 2. 新增：解析高德景点工具返回结果，转为大模型易读的纯文本
def _format_scenic_spots(tool_result: str) -> str:
    """
    解析search_hot_scenic_spots的返回JSON，转为纯文本格式
    格式：1) 景点名（所属区域）- 类型；2) 景点名（所属区域）- 类型；...
    """
    try:
        result = json.loads(tool_result)
        # 工具调用成功则提取景点数据
        if result.get("ok") and result.get("data", {}).get("spots"):
            spots = result["data"]["spots"]
            spot_texts = []
            for idx, spot in enumerate(spots, 1):
                name = spot.get("name", "未知景点")
                adname = spot.get("adname", "未知区域")
                spot_type = spot.get("type", "旅游景点").split(";")[0]  # 裁剪类型冗余字段
                spot_texts.append(f"{idx}) {name}（{adname}）- {spot_type}")
            return "\n".join(spot_texts) if spot_texts else "暂无热门景点信息"
        else:
            # 工具调用失败返回提示
            return f"景点获取失败：{result.get('error', '未知原因')}，将为你推荐经典行程"
    except Exception as e:
        return f"景点信息解析失败：{str(e)}，将为你推荐经典行程"


def _llm_recommend_destinations_text(user_input: str, profile_json: str, top_k: int) -> str:
    """
    只生成“目的地推荐”文本（不输出JSON）
    【原有逻辑不变，未做任何修改】
    """
    model = get_model(temperature=0.6)

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "你是专业旅行顾问。你将收到用户需求与profile(JSON字符串)。"
         "你的任务：给出TopK个目的地推荐，并说明理由。"
         "只输出纯文本，不要输出JSON，不要输出代码块，不要输出markdown标题符号。"
         "不要编造精确价格、精确营业时间；如涉及费用用“约/大致/可能”措辞，并建议以官方为准。\n\n"
         "输出格式必须为：\n"
         "【推荐目的地】\n"
         "1) 目的地名（国内城市/区域）\n"
         "   - 适配理由：...\n"
         "   - 预算/天数匹配：...\n"
         "2) ...\n"
         "3) ...\n"
         "【我需要确认】最多2个追问，用于推进下一步（是否已确定目的地/出发地/更偏好自然或人文等）。"
        ),
        ("human",
         "用户需求：{user_input}\n"
         "当前profile(JSON)：{profile_json}\n"
         "TopK：{top_k}\n")
    ])

    chain = prompt | model | StrOutputParser()
    text = chain.invoke({
        "user_input": user_input or "帮我推荐一个合适的国内旅游目的地",
        "profile_json": _compact_profile(profile_json),
        "top_k": top_k,
    }).strip()

    if not text:
        return (
            "【推荐目的地】\n"
            "1) 成都\n   - 适配理由：美食与人文兼具，城市交通方便\n   - 预算/天数匹配：多数行程可灵活安排\n"
            f"【我需要确认】你大概想去几天？从哪里出发？"
        )
    return text


# 3. 核心改造：_llm_plan_itinerary_text 新增高德景点调用+数据透传
def _llm_plan_itinerary_text(destination: str, days: int, profile_json: str) -> str:
    """
    生成“行程规划”文本（不输出JSON）
    【改造后】先调用高德工具获取真实景点，再基于景点生成行程，工具失败则降级原有逻辑
    """
    model = get_model(temperature=0.4)
    # 第一步：调用高德景点工具，获取当前目的地的热门景点
    # 调用工具（limit=15，获取足够多的景点供大模型选择，工具内部会限制20以内）
    spot_tool_result = search_hot_scenic_spots.invoke({"city": destination, "limit": 15})
    # 解析工具结果为纯文本格式
    scenic_spots_text = _format_scenic_spots(spot_tool_result)

    # 第二步：改造prompt，强制大模型使用真实景点数据
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "你是资深旅行行程规划师。你将收到目的地、行程天数、用户profile(JSON字符串)、以及该城市**真实热门景点清单**。"
         "你的核心要求：**行程中所有景点必须从提供的真实热门景点清单中选择**，严禁编造任何景点/街区/餐饮点！"
         "请输出可执行、节奏不赶的行程安排，结合景点的区域分布规划动线（减少折返）。"
         "只输出纯文本，不要输出JSON，不要输出代码块。"
         "不要编造精确门票价格与精确地址；若不确定，用“约/建议现场或官方确认”。\n\n"
         "强约束：\n"
         "1) 每天分：上午/中午/下午/晚上；\n"
         "2) 每个时段给1-2个点（仅从景点清单选），并解释为什么这样排（交通/动线/体力/区域分布）；\n"
         "3) 每天给1条“可替换选项”（仅从景点清单选同区域景点）；\n"
         "4) 结尾给“住宿建议区域”（结合景点分布）和“交通建议”（一句话即可）。\n\n"
         "输出格式必须为：\n"
         "【{destination} {days}天行程建议】\n"
         "Day1：...\n"
         "Day2：...\n"
         "...\n"
         "【备选与注意】...\n"
         "【我需要确认】最多2个问题（例如：是否亲子/是否早起/是否需要把美食作为主线）。"
        ),
        ("human",
         "目的地：{destination}\n"
         "天数：{days}\n"
         "当前profile(JSON)：{profile_json}\n"
         "该城市真实热门景点清单：\n{scenic_spots_text}\n")  # 新增：透传真实景点数据
    ])

    chain = prompt | model | StrOutputParser()
    text = chain.invoke({
        "destination": destination.strip(),
        "days": int(days),
        "profile_json": _compact_profile(profile_json),
        "scenic_spots_text": scenic_spots_text  # 传入解析后的景点文本
    }).strip()

    # 原有兜底逻辑不变
    if not text:
        return (
            f"【{destination} {days}天行程建议】\n"
            "Day1：上午城市核心街区随走随吃；中午本地特色餐；下午人文景点；晚上夜市/夜景。\n"
            "Day2：上午自然或主题景点；中午简餐；下午购物/博物馆；晚上返程或轻松散步。\n"
            "【备选与注意】如遇下雨优先安排室内博物馆/商圈。\n"
            "【我需要确认】你更偏好打卡密集还是慢节奏？"
        )
    return text


@tool
def recommend_and_plan_trip(
    user_input: str = "",
    profile_json: str = "",
    mode: str = "recommend",   # recommend | plan | one_click
    destination: str = "",
    days: int = 3,
    top_k: int = 3
) -> str:
    """
    执行型旅行工具：
    - mode="recommend": 基于用户需求+profile给TopK目的地推荐（纯文本）
    - mode="plan": 基于 destination + days + profile + 真实景点数据输出行程（纯文本）
    - mode="one_click": 先推荐1个目的地，再基于真实景点数据给行程（纯文本）
    返回：tool_return协议 JSON字符串，其中 data.text 为可直接回复用户的文本
    """
    mode = (mode or "recommend").strip().lower()
    days = max(1, min(int(days), 10))
    top_k = max(1, min(int(top_k), 5))

    # 轻度解析profile（主要用于兜底判断）
    _ = _safe_json(profile_json)

    try:
        if mode == "plan":
            if not destination.strip():
                return tool_return(False, error="mode=plan 需要提供 destination", source="llm-trip")
            # 直接调用改造后的行程函数（内部已集成景点调用）
            text = _llm_plan_itinerary_text(destination=destination, days=days, profile_json=profile_json)
            return tool_return(True, data={"text": text, "mode": mode}, source="llm-trip")

        if mode == "one_click":
            # 先推荐（原有逻辑不变）
            rec_text = _llm_recommend_destinations_text(user_input=user_input, profile_json=profile_json, top_k=top_k)
            model = get_model(temperature=0.1)
            pick_prompt = ChatPromptTemplate.from_messages([
                ("system",
                 "从用户的推荐清单中选出排名第1的目的地名称。只输出目的地名称（例如：成都），不要输出任何其它字符。"),
                ("human", "推荐清单文本：\n{rec_text}\n")
            ])
            pick_chain = pick_prompt | model | StrOutputParser()
            picked = pick_chain.invoke({"rec_text": rec_text}).strip()
            picked = picked.splitlines()[0].strip() if picked else ""

            if not picked or len(picked) > 12:
                picked = destination.strip() or "成都"

            # 调用改造后的行程函数（基于真实景点生成）
            plan_text = _llm_plan_itinerary_text(destination=picked, days=days, profile_json=profile_json)
            text = rec_text + "\n\n" + plan_text
            return tool_return(True, data={"text": text, "mode": mode, "picked_destination": picked}, source="llm-trip")

        # 默认 recommend（原有逻辑不变，推荐阶段暂不调用景点工具）
        rec_text = _llm_recommend_destinations_text(user_input=user_input, profile_json=profile_json, top_k=top_k)
        return tool_return(True, data={"text": rec_text, "mode": "recommend"}, source="llm-trip")

    except Exception as e:
        return tool_return(False, error=f"旅行规划工具失败：{str(e)}", source="llm-trip")