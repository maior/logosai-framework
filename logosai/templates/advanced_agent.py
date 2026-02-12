"""
LogosAI 고급 에이전트 템플릿

데코레이터와 고급 기능을 사용한 에이전트 구현 예제입니다.
"""

import asyncio
from typing import Dict, Any
from logosai import (
    ConversationalAgent, AgentConfig, AgentType,
    conversational_agent, auto_param_collection, visualizable,
    parameter, auto_validate, smart_caching, monitoring,
    ParameterDefinition, ValidationRule
)


@conversational_agent(
    name="Advanced Weather Agent",
    agent_type=AgentType.WEATHER,
    description="고급 날씨 에이전트 - 파라미터 수집과 시각화 지원"
)
@auto_param_collection(['location'])
@visualizable(
    chart_type='line',
    title='온도 변화 추이',
    x_axis='날짜',
    y_axis='온도 (°C)',
    auto_generate=True
)
@parameter(
    name="period",
    description="조회 기간",
    required=False,
    parameter_type="string", 
    default_value="today",
    validation=ValidationRule(
        rule_type="choices",
        rule_value=["today", "tomorrow", "week", "month"],
        error_message="today, tomorrow, week, month 중 하나를 선택하세요"
    ),
    collection_prompt="어떤 기간의 날씨를 원하시나요? (today/tomorrow/week/month)"
)
@parameter(
    name="units",
    description="온도 단위",
    required=False,
    parameter_type="string",
    default_value="celsius",
    validation="^(celsius|fahrenheit)$"
)
@auto_validate()
@smart_caching(ttl_seconds=300)  # 5분 캐시
@monitoring(enable_metrics=True, log_level="INFO")
class AdvancedWeatherAgent(ConversationalAgent):
    """고급 날씨 에이전트"""
    
    async def execute_with_parameters(self, query: str, parameters: Dict[str, Any]) -> Any:
        """날씨 정보 조회 실행"""
        location = parameters.get('location', '서울')
        period = parameters.get('period', 'today')
        units = parameters.get('units', 'celsius')
        
        # 모의 날씨 데이터 생성
        if period == "week":
            # 일주일 데이터
            weather_data = {
                "location": location,
                "period": period,
                "data": {
                    "2024-01-01": 5.2,
                    "2024-01-02": 7.1,
                    "2024-01-03": 6.8,
                    "2024-01-04": 4.5,
                    "2024-01-05": 3.2,
                    "2024-01-06": 2.8,
                    "2024-01-07": 4.1
                },
                "units": units
            }
            
            # 차트 데이터 자동 생성 (visualizable 데코레이터가 처리)
            return weather_data
        else:
            # 단일 날 데이터
            return {
                "location": location,
                "period": period,
                "temperature": 6.5 if units == "celsius" else 43.7,
                "condition": "맑음",
                "humidity": 65,
                "units": units
            }


@conversational_agent(
    name="Math Calculator Agent",
    agent_type=AgentType.CALCULATION,
    description="수학 계산 에이전트"
)
@parameter(
    name="expression",
    description="계산할 수식",
    required=True,
    validation=ValidationRule(
        rule_type="regex",
        rule_value=r"^[0-9+\-*/().\s]+$",
        error_message="올바른 수학 표현식을 입력하세요 (숫자와 +, -, *, /, (, )만 허용)"
    )
)
@parameter(
    name="precision",
    description="소수점 자릿수",
    required=False,
    parameter_type="number",
    default_value=2,
    validation=ValidationRule(
        rule_type="range",
        rule_value=(0, 10),
        error_message="0-10 사이의 값을 입력하세요"
    )
)
@auto_validate()
@monitoring(enable_metrics=True)
class MathAgent(ConversationalAgent):
    """수학 계산 에이전트"""
    
    async def execute_with_parameters(self, query: str, parameters: Dict[str, Any]) -> Any:
        """수학 계산 실행"""
        expression = parameters.get('expression')
        precision = int(parameters.get('precision', 2))
        
        try:
            # 안전한 수식 계산 (eval 대신 더 안전한 방법 사용 권장)
            result = eval(expression)
            formatted_result = round(float(result), precision)
            
            return {
                "expression": expression,
                "result": formatted_result,
                "precision": precision,
                "success": True
            }
        except Exception as e:
            return {
                "expression": expression,
                "error": str(e),
                "success": False
            }


@conversational_agent(
    name="Data Analysis Agent",
    agent_type=AgentType.ANALYSIS,
    description="데이터 분석 및 시각화 에이전트"
)
@visualizable(
    chart_type='bar',
    title='데이터 분석 결과',
    auto_generate=True,
    color_scheme='rainbow'
)
@parameter(
    name="data",
    description="분석할 데이터 (JSON 형식)",
    required=True,
    parameter_type="string"
)
@parameter(
    name="analysis_type",
    description="분석 유형",
    required=False,
    default_value="basic",
    validation=ValidationRule(
        rule_type="choices",
        rule_value=["basic", "statistical", "trend"],
        error_message="basic, statistical, trend 중 하나를 선택하세요"
    )
)
@auto_validate()
@smart_caching(ttl_seconds=600)  # 10분 캐시
class DataAnalysisAgent(ConversationalAgent):
    """데이터 분석 에이전트"""
    
    async def execute_with_parameters(self, query: str, parameters: Dict[str, Any]) -> Any:
        """데이터 분석 실행"""
        import json
        
        data_str = parameters.get('data')
        analysis_type = parameters.get('analysis_type', 'basic')
        
        try:
            # JSON 데이터 파싱
            data = json.loads(data_str)
            
            if analysis_type == "basic":
                return self._basic_analysis(data)
            elif analysis_type == "statistical":
                return self._statistical_analysis(data)
            elif analysis_type == "trend":
                return self._trend_analysis(data)
                
        except json.JSONDecodeError:
            return {
                "error": "유효하지 않은 JSON 형식입니다",
                "success": False
            }
    
    def _basic_analysis(self, data: Any) -> Dict[str, Any]:
        """기본 분석"""
        if isinstance(data, dict):
            return {
                "analysis_type": "basic",
                "data_type": "dictionary",
                "key_count": len(data),
                "keys": list(data.keys()),
                "values": list(data.values()),
                "success": True
            }
        elif isinstance(data, list):
            return {
                "analysis_type": "basic", 
                "data_type": "list",
                "item_count": len(data),
                "first_items": data[:5],
                "success": True
            }
        else:
            return {
                "analysis_type": "basic",
                "data_type": type(data).__name__,
                "value": data,
                "success": True
            }
    
    def _statistical_analysis(self, data: Any) -> Dict[str, Any]:
        """통계 분석"""
        if isinstance(data, dict):
            numeric_values = [v for v in data.values() if isinstance(v, (int, float))]
            if numeric_values:
                return {
                    "analysis_type": "statistical",
                    "count": len(numeric_values),
                    "sum": sum(numeric_values),
                    "average": sum(numeric_values) / len(numeric_values),
                    "min": min(numeric_values),
                    "max": max(numeric_values),
                    "data": dict(zip(data.keys(), data.values())),  # 차트용
                    "success": True
                }
        
        return {"error": "통계 분석할 수 있는 숫자 데이터가 없습니다", "success": False}
    
    def _trend_analysis(self, data: Any) -> Dict[str, Any]:
        """트렌드 분석"""
        if isinstance(data, dict):
            values = [v for v in data.values() if isinstance(v, (int, float))]
            if len(values) > 1:
                trend = "증가" if values[-1] > values[0] else "감소"
                return {
                    "analysis_type": "trend",
                    "trend": trend,
                    "start_value": values[0],
                    "end_value": values[-1],
                    "change": values[-1] - values[0],
                    "data": data,  # 차트용
                    "success": True
                }
        
        return {"error": "트렌드 분석할 수 있는 데이터가 없습니다", "success": False}


async def demo_agents():
    """에이전트 데모"""
    print("=== LogosAI 고급 에이전트 데모 ===\n")
    
    # 1. 날씨 에이전트
    print("1. 날씨 에이전트 테스트")
    weather_agent = AdvancedWeatherAgent()
    await weather_agent.initialize()
    
    result = await weather_agent.process({
        "query": "서울 일주일 날씨를 그래프로 보여줘",
        "parameters": {
            "location": "서울",
            "period": "week"
        }
    })
    
    print(f"결과: {result.message}")
    if result.content and isinstance(result.content, dict):
        if 'chart_data' in result.content:
            print("✅ 차트 데이터 생성됨")
        else:
            print("📊 데이터:", list(result.content.get('data', {}).keys())[:3])
    
    await weather_agent.shutdown()
    print()
    
    # 2. 수학 에이전트
    print("2. 수학 에이전트 테스트")
    math_agent = MathAgent()
    await math_agent.initialize()
    
    result = await math_agent.process({
        "query": "계산해줘",
        "parameters": {
            "expression": "2 + 3 * 4",
            "precision": 2
        }
    })
    
    print(f"결과: {result.message}")
    if result.content:
        print(f"계산: {result.content.get('expression')} = {result.content.get('result')}")
    
    await math_agent.shutdown()
    print()
    
    # 3. 데이터 분석 에이전트
    print("3. 데이터 분석 에이전트 테스트")
    analysis_agent = DataAnalysisAgent()
    await analysis_agent.initialize()
    
    sample_data = '{"1월": 100, "2월": 150, "3월": 200, "4월": 180, "5월": 220}'
    result = await analysis_agent.process({
        "query": "데이터 분석해줘",
        "parameters": {
            "data": sample_data,
            "analysis_type": "statistical"
        }
    })
    
    print(f"결과: {result.message}")
    if result.content:
        content = result.content
        if content.get('success'):
            print(f"평균: {content.get('average')}")
            print(f"최대값: {content.get('max')}")
            print(f"최소값: {content.get('min')}")
    
    await analysis_agent.shutdown()
    print("\n=== 데모 완료 ===")


if __name__ == "__main__":
    asyncio.run(demo_agents())