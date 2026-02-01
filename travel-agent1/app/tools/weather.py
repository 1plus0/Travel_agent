import requests
import json
from bs4 import BeautifulSoup
import sys
import os

from app.tools.utils import tool_return
from langchain_core.tools import tool

from datetime import date, datetime
import re

CITY_CODE_FILE = r"app\tools\city_codes.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "http://www.weather.com.cn/"
}


def normalize_date_cn(day_text: str, today: date) -> str:
    """
    把 '29日' / '29日（周四）' 转成 YYYY-MM-DD
    规则：如果 day < today.day 且今天接近月底，则认为跨月（简单实用版）
    """
    m = re.search(r"(\d{1,2})日", day_text)
    if not m:
        return ""  # 解析不到就空

    d = int(m.group(1))
    y = today.year
    mo = today.month

    # 简单跨月判断：如果抓到的日数 < 今天日数，认为是下个月
    if d < today.day:
        if mo == 12:
            y += 1
            mo = 1
        else:
            mo += 1

    return f"{y:04d}-{mo:02d}-{d:02d}"


def load_city_codes():
    """读取本地城市代码JSON文件"""
    try:
        with open(CITY_CODE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"__error__": f"未找到城市代码文件 {CITY_CODE_FILE}，请先运行 crawl_city_codes.py"}
    except Exception as e:
        return {"__error__": f"读取城市代码文件失败：{str(e)}"}

def _json(obj) -> str:
    """统一把工具输出转成 JSON 字符串（确保 tool message content 是 string）"""
    return json.dumps(obj, ensure_ascii=False)

@tool
def get_15d_weather(city_name: str) -> str:
    """
    读取本地城市代码，爬取15天天气
    返回值必须是 string（JSON 字符串）
    """
    city_codes = load_city_codes()
    if not city_codes:
        return tool_return({"error": "城市代码文件加载失败"})

    city_code = None
    if city_name in city_codes:
        city_code = city_codes[city_name]
    else:
        for name, code in city_codes.items():
            if city_name in name or name in city_name:
                city_code = code
                break

    if not city_code:
        return tool_return({"error": f"未找到{city_name}的城市代码，请检查名称或补充到 {CITY_CODE_FILE}"})

    weather_url = f"http://www.weather.com.cn/weather15d/{city_code}.shtml"

    try:
        resp = requests.get(weather_url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        fifteen_days = soup.find("ul", class_="t clearfix")
        if not fifteen_days:
            tc = soup.find("div", class_="tc_content")
            fifteen_days = tc.find("ul") if tc else None

        if not fifteen_days:
            return tool_return({"error": f"{city_name}的15天预报页面结构不匹配"})

        weather_15d = []
        li_list = fifteen_days.find_all("li")[:15]
        for li in li_list:
            day_info = {}

            date_tag = li.find("span", class_="time") or li.find("h3")
            #修改后
            raw_date = date_tag.text.strip() if date_tag else ""
            day_info["date_raw"] = raw_date
            day_info["date"] = normalize_date_cn(raw_date, date.today())


            weather_tag = li.find("span", class_="wea") or li.find("p", class_="wea")
            day_info["weather"] = weather_tag.text.strip() if weather_tag else ""

            temp_tag = li.find("span", class_="tem") or li.find("p", class_="tem")
            if temp_tag:
                temp_text = temp_tag.get_text(strip=True)
                if "~" in temp_text:
                    a, b = temp_text.split("~", 1)
                    day_info["temp_min"] = a.replace("℃", "").strip()
                    day_info["temp_max"] = b.replace("℃", "").strip()
                else:
                    day_info["temp"] = temp_text
                    day_info["temp_min"] = ""
                    day_info["temp_max"] = ""
            else:
                day_info["temp_min"] = ""
                day_info["temp_max"] = ""

            wind_tag = li.find("span", class_="wind") or li.find("p", class_="wind")
            day_info["wind"] = wind_tag.get_text(strip=True) if wind_tag else ""

            weather_15d.append(day_info)

        return tool_return(
            ok=True,
            data={
            "city": city_name,
            "city_code": city_code,
            "weather_15d": weather_15d,
            "total_days": len(weather_15d)
            },
            source="amap"
        )
        

    except Exception as e:
        return tool_return(
        ok=False,
        error={"error": f"爬取{city_name}15天天气失败：{str(e)}"},
        source="amap"
        )
        


if __name__ == "__main__":
    print("===== 绵阳15天天气 =====")
    print(get_15d_weather("绵阳"))

    print("\n===== 成都15天天气 =====")
    print(get_15d_weather("成都"))
