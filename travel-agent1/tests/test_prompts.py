import pytest

from app.prompts.prompt_runner import run_prompt
from app.prompts.renderer import render_prompt


def test_render_prompt_success():
    """验证模板渲染填充变量正常工作。"""
    messages = render_prompt(
        "travel_plan",
        city="上海",
        days=3,
        preferences="美食, 文化",
        budget="中等",
    )
    assert messages[0]["role"] == "system"
    assert "智能出行" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "上海" in messages[1]["content"]
    assert "3 天" in messages[1]["content"]


def test_render_prompt_missing_var():
    """缺少必填变量时应抛出友好错误。"""
    with pytest.raises(ValueError) as err:
        render_prompt("travel_plan", city="上海", days=3, preferences="美食")
    assert "missing var" in str(err.value)


@pytest.mark.live
def test_run_prompt_live():
    """
    集成测试：直接调用真实大模型，需有效的 DEEPSEEK_API_KEY/DEEPSEEK_BASE_URL。
    若环境未配置密钥，可通过 -m "live" 选择性运行或配置后再跑。
    """
    result = run_prompt(
        "travel_plan",
        city="北京",
        days=2,
        preferences="博物馆",
        budget="节省",
    )
    assert isinstance(result, str)
    assert len(result.strip()) > 0
    print("LLM response:", result)


#运行方式： 
# • 仅跑基础单测（不触发真实调用）：pytest tests/test_prompts.py  
# • 跑包含真实大模型调用的集成测试：pytest -m live tests/test_prompts.py
# pytest -s -m live tests/test_prompts.py