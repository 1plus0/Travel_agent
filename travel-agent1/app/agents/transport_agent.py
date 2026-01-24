from app.agents.base import get_model
from typing import Dict, List, Optional
import json
import asyncio

class TransportAgent:
    """交通比价智能体"""
    
    def __init__(self):
        self.llm = get_model(temperature=0.1)  # 使用 base.py 的统一方法
    
    async def get_transport_plan(self, departure: str, destination: str, 
                               date: str, transport_types: List[str] = None) -> Dict:
        """
        获取交通方案并比价
        
        Args:
            departure: 出发地
            destination: 目的地  
            date: 出行日期 (YYYY-MM-DD)
            transport_types: 交通方式列表 ['train', 'flight', 'bus']
        """
        if transport_types is None:
            transport_types = ['train', 'flight']
        
        results = {}
        
        # 并发调用各种交通工具API
        tasks = []
        if 'train' in transport_types:
            tasks.append(self._get_train_info(departure, destination, date))
        
        if 'flight' in transport_types:
            tasks.append(self._get_flight_info(departure, destination, date))
        
        # 并发执行查询
        query_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 整理结果
        idx = 0
        if 'train' in transport_types:
            results['train'] = query_results[idx] if not isinstance(query_results[idx], Exception) else {"error": str(query_results[idx])}
            idx += 1
        
        if 'flight' in transport_types:
            results['flight'] = query_results[idx] if not isinstance(query_results[idx], Exception) else {"error": str(query_results[idx])}
        
        # 使用LLM分析并给出推荐
        analysis = await self._analyze_transport_options(results, departure, destination)
        
        return {
            "departure": departure,
            "destination": destination,
            "date": date,
            "options": results,
            "analysis": analysis
        }
    
    async def _get_train_info(self, departure: str, destination: str, date: str):
        """调用12306 MCP或API获取火车票信息"""
        # 暂时使用模拟数据，后续替换为真实的12306 MCP调用
        await asyncio.sleep(0.5)  # 模拟网络延迟
        
        return {
            "source": "12306",
            "trains": [
                {
                    "train_no": "G1234",
                    "departure_time": "08:00",
                    "arrival_time": "14:30",
                    "duration": "6小时30分",
                    "price": {
                        "second_class": 553.5,
                        "first_class": 884.5,
                        "business_class": 1748.5
                    },
                    "status": "有票",
                    "departure_station": departure,
                    "arrival_station": destination
                },
                {
                    "train_no": "D5678",
                    "departure_time": "14:00", 
                    "arrival_time": "22:45",
                    "duration": "8小时45分",
                    "price": {
                        "second_class": 423.5,
                        "first_class": 678.5
                    },
                    "status": "有票",
                    "departure_station": departure,
                    "arrival_station": destination
                }
            ]
        }
    
    async def _get_flight_info(self, departure: str, destination: str, date: str):
        """调用航班查询API"""
        # 暂时使用模拟数据，后续替换为真实的航班查询 MCP调用
        await asyncio.sleep(0.8)  # 模拟网络延迟
        
        return {
            "source": "航班查询",
            "flights": [
                {
                    "flight_no": "CA1234",
                    "airline": "中国国际航空",
                    "departure_time": "10:30",
                    "arrival_time": "13:45",
                    "duration": "3小时15分",
                    "price": {
                        "economy": 890,
                        "business": 2890
                    },
                    "status": "有票",
                    "departure_airport": f"{departure}机场",
                    "arrival_airport": f"{destination}机场"
                },
                {
                    "flight_no": "MU5678",
                    "airline": "东方航空",
                    "departure_time": "16:20",
                    "arrival_time": "19:55",
                    "duration": "3小时35分",
                    "price": {
                        "economy": 750,
                        "business": 2100
                    },
                    "status": "有票",
                    "departure_airport": f"{departure}机场",
                    "arrival_airport": f"{destination}机场"
                }
            ]
        }
    
    async def _analyze_transport_options(self, transport_data: Dict, departure: str, destination: str):
        """使用LLM分析交通方案"""
        prompt = f"""
        请分析以下交通方案，从时间、价格、舒适度等维度给出推荐：
        
        出发地：{departure}
        目的地：{destination}
        
        交通方案数据：
        {json.dumps(transport_data, ensure_ascii=False, indent=2)}
        
        请按以下格式给出分析：
        1. **最快到达方案**：推荐具体班次及原因
        2. **最经济方案**：推荐具体班次及原因  
        3. **性价比最高方案**：综合时间和价格推荐
        4. **综合推荐**：根据一般旅客需求给出最佳建议
        
        请用简洁明了的语言回答。
        """
        
        response = await self.llm.ainvoke(prompt)
        return response.content