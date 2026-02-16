"""
LogosAI LLM 에이전트 레지스트리 모듈

이 모듈은 LLM이 에이전트를 선택하고 호출할 수 있도록 에이전트 레지스트리와
JSON 형태의 연결 인터페이스를 제공합니다.
"""

import json
import logging
import asyncio
from enum import Enum
from typing import Dict, List, Any, Optional, Union, Callable

from .agent import LogosAIAgent
from .agent_types import AgentType, AgentResponseType
from .types import AgentResponse
from .config import AgentConfig
from .agent_bundler import BundleType

# 로깅 설정
logger = logging.getLogger(__name__)


class AgentCapability(Enum):
    """에이전트 기능 정의"""
    TEXT_GENERATION = "text_generation"
    INTERNET_SEARCH = "internet_search"
    DATA_ANALYSIS = "data_analysis"
    CODE_GENERATION = "code_generation"
    IMAGE_GENERATION = "image_generation"
    TRANSLATION = "translation"
    CLASSIFICATION = "classification"
    RECOMMENDATION = "recommendation"
    QA = "question_answering"
    SUMMARIZATION = "summarization"
    CALCULATION = "calculation"


class AgentRegistryEntry:
    """에이전트 레지스트리 항목"""
    def __init__(
        self,
        agent_id: str,
        name: str,
        description: str,
        agent_type: AgentType,
        bundle_type: BundleType,
        capabilities: List[AgentCapability],
        examples: List[Dict[str, str]] = None,
        parameters: Dict[str, Any] = None,
        metadata: Dict[str, Any] = None
    ):
        self.agent_id = agent_id
        self.name = name
        self.description = description
        self.agent_type = agent_type
        self.bundle_type = bundle_type
        self.capabilities = capabilities
        self.examples = examples or []
        self.parameters = parameters or {}
        self.metadata = metadata or {}
        self._agent_instance = None

    def to_dict(self) -> Dict[str, Any]:
        """에이전트 정보를 딕셔너리로 변환"""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "type": str(self.agent_type),
            "bundle_type": self.bundle_type.value,
            "capabilities": [c.value for c in self.capabilities],
            "examples": self.examples,
            "parameters": self.parameters,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentRegistryEntry':
        """딕셔너리에서 에이전트 정보 생성"""
        capabilities = [
            AgentCapability(c) if isinstance(c, str) else c 
            for c in data.get("capabilities", [])
        ]
        
        agent_type = AgentType.from_string(data.get("type", "CUSTOM"))
        bundle_type = BundleType(data.get("bundle_type", BundleType.MANAGED_SOURCE.value))
        
        return cls(
            agent_id=data.get("agent_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            agent_type=agent_type,
            bundle_type=bundle_type,
            capabilities=capabilities,
            examples=data.get("examples", []),
            parameters=data.get("parameters", {}),
            metadata=data.get("metadata", {})
        )

    async def get_agent(self) -> LogosAIAgent:
        """에이전트 인스턴스 가져오기"""
        if self._agent_instance is None:
            # 에이전트 로드 로직 (실제 구현에서는 번들 타입에 따라 로드)
            from .agent_loader import load_agent
            self._agent_instance = await load_agent(self.agent_id)
            await self._agent_instance.initialize()
            
        return self._agent_instance


class AgentRegistry:
    """에이전트 레지스트리"""
    def __init__(self):
        self.agents: Dict[str, AgentRegistryEntry] = {}
        self.initialized = False
        
    async def initialize(self) -> bool:
        """레지스트리 초기화"""
        if self.initialized:
            return True
            
        try:
            # 기본 에이전트 로드 (실제 구현에서는 저장된 레지스트리에서 로드)
            await self._load_registry()
            self.initialized = True
            return True
        except Exception as e:
            logger.error(f"에이전트 레지스트리 초기화 오류: {str(e)}")
            return False
            
    async def _load_registry(self) -> None:
        """저장된 레지스트리 로드"""
        # 실제 구현에서는 데이터베이스나 파일에서 로드
        # 이 예제에서는 메모리에 기본값 설정
        pass
        
    def register_agent(self, entry: AgentRegistryEntry) -> bool:
        """에이전트 등록"""
        if entry.agent_id in self.agents:
            logger.warning(f"이미 등록된 에이전트 ID: {entry.agent_id}")
            return False
            
        self.agents[entry.agent_id] = entry
        logger.info(f"에이전트 등록 완료: {entry.name} (ID: {entry.agent_id})")
        return True
        
    def unregister_agent(self, agent_id: str) -> bool:
        """에이전트 등록 해제"""
        if agent_id not in self.agents:
            logger.warning(f"등록되지 않은 에이전트 ID: {agent_id}")
            return False
            
        del self.agents[agent_id]
        logger.info(f"에이전트 등록 해제 완료: {agent_id}")
        return True
        
    def get_agent_entry(self, agent_id: str) -> Optional[AgentRegistryEntry]:
        """에이전트 항목 가져오기"""
        return self.agents.get(agent_id)
        
    def find_agents_by_capability(self, capability: Union[AgentCapability, str]) -> List[AgentRegistryEntry]:
        """기능으로 에이전트 찾기"""
        if isinstance(capability, str):
            capability = AgentCapability(capability)
            
        return [
            agent for agent in self.agents.values() 
            if capability in agent.capabilities
        ]
        
    def find_agents_by_type(self, agent_type: Union[AgentType, str]) -> List[AgentRegistryEntry]:
        """유형으로 에이전트 찾기"""
        if isinstance(agent_type, str):
            agent_type = AgentType.from_string(agent_type)
            
        return [
            agent for agent in self.agents.values() 
            if agent.agent_type == agent_type
        ]
        
    def get_all_agents(self) -> List[AgentRegistryEntry]:
        """모든 에이전트 가져오기"""
        return list(self.agents.values())
        
    def get_llm_registry_json(self) -> str:
        """LLM용 레지스트리 JSON 가져오기"""
        registry_data = {
            "agents": [agent.to_dict() for agent in self.agents.values()]
        }
        return json.dumps(registry_data, ensure_ascii=False, indent=2)


class LLMAgentSelector:
    """LLM 에이전트 선택기"""
    def __init__(self, registry: AgentRegistry):
        self.registry = registry
        
    def get_agent_descriptions_for_llm(self) -> str:
        """LLM에 제공할 에이전트 설명 생성"""
        agents = self.registry.get_all_agents()
        
        descriptions = []
        for idx, agent in enumerate(agents, 1):
            capabilities = ", ".join([c.value for c in agent.capabilities])
            description = f"{idx}. {agent.name}: {agent.description} (기능: {capabilities})"
            
            # 예시 추가
            if agent.examples:
                examples_text = "\n   - 예시: " + "\n   - 예시: ".join([
                    f"입력: '{ex.get('input', '')}', 출력: '{ex.get('output', '')}'"
                    for ex in agent.examples[:2]  # 처음 2개 예시만
                ])
                description += examples_text
                
            descriptions.append(description)
            
        return "\n".join(descriptions)
        
    def generate_llm_selection_prompt(self, user_query: str) -> str:
        """LLM에 제공할 에이전트 선택 프롬프트 생성"""
        agent_descriptions = self.get_agent_descriptions_for_llm()
        
        prompt = f"""
사용자 질의: "{user_query}"

사용 가능한 에이전트:
{agent_descriptions}

위 사용자 질의를 처리하기 위해 가장 적합한 에이전트를 선택하세요. 
에이전트를 선택한 이유와 함께 다음 JSON 형식으로 응답하세요:

```json
{{
  "selected_agent_idx": <에이전트 인덱스>,
  "reason": "<선택 이유>",
  "parameters": {{
    // 에이전트에 전달할 파라미터
  }}
}}
```

가장 적합한 에이전트가 없으면 다음과 같이 응답하세요:

```json
{{
  "selected_agent_idx": null,
  "reason": "<이유>"
}}
```
"""
        return prompt


class LLMAgentRouter:
    """LLM 에이전트 라우터"""
    def __init__(self, registry: AgentRegistry, llm_client = None):
        self.registry = registry
        self.selector = LLMAgentSelector(registry)
        self.llm_client = llm_client
        
    async def route_query(self, user_query: str, context: Dict[str, Any] = None) -> AgentResponse:
        """LLM을 사용하여 쿼리를 적절한 에이전트로 라우팅"""
        if not self.llm_client:
            return AgentResponse.error("LLM 클라이언트가 설정되지 않았습니다.")
            
        # 에이전트 선택 프롬프트 생성
        selection_prompt = self.selector.generate_llm_selection_prompt(user_query)
        
        try:
            # LLM 호출하여 에이전트 선택
            llm_response = await self._call_llm(selection_prompt)
            
            # JSON 응답 파싱
            selection_data = self._parse_llm_response(llm_response)
            
            # 선택된 에이전트가 없는 경우
            if selection_data.get("selected_agent_idx") is None:
                return AgentResponse.error(
                    f"적합한 에이전트를 찾을 수 없습니다: {selection_data.get('reason', '알 수 없는 이유')}"
                )
                
            # 에이전트 인덱스 가져오기
            agent_idx = selection_data.get("selected_agent_idx")
            
            # 유효한 인덱스 검사
            agents = self.registry.get_all_agents()
            if not (1 <= agent_idx <= len(agents)):
                return AgentResponse.error(f"잘못된 에이전트 인덱스: {agent_idx}")
                
            # 선택된 에이전트 가져오기
            selected_agent_entry = agents[agent_idx - 1]  # 인덱스는 1부터 시작하므로 -1
            
            # 에이전트 인스턴스 가져오기
            agent = await selected_agent_entry.get_agent()
            
            # 선택된 에이전트에 쿼리 전달
            agent_context = context or {}
            agent_context.update({
                "selected_by_llm": True,
                "selection_reason": selection_data.get("reason", ""),
                "llm_parameters": selection_data.get("parameters", {})
            })
            
            # 에이전트 호출
            result = await agent.process_query(user_query, agent_context)
            
            # 결과에 메타데이터 추가
            if result.metadata is None:
                result.metadata = {}
            result.metadata["selected_agent"] = {
                "id": selected_agent_entry.agent_id,
                "name": selected_agent_entry.name,
                "reason": selection_data.get("reason", "")
            }
            
            return result
            
        except Exception as e:
            logger.exception("에이전트 라우팅 중 오류 발생")
            return AgentResponse.error(f"에이전트 라우팅 오류: {str(e)}")
            
    async def _call_llm(self, prompt: str) -> str:
        """LLM 호출 (실제 구현은 사용하는 LLM 서비스에 따라 다름)"""
        # 이 예제에서는 OpenAI API를 사용한다고 가정
        try:
            from openai import AsyncOpenAI
            
            # LLM 클라이언트가 AsyncOpenAI 인스턴스라고 가정
            response = await self.llm_client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2
            )
            
            return response.choices[0].message.content
            
        except ImportError:
            # OpenAI 모듈이 없는 경우
            return """```json
{
  "selected_agent_idx": 1,
  "reason": "사용자 질의에 가장 적합한 에이전트로 판단됩니다.",
  "parameters": {}
}
```"""
            
    def _parse_llm_response(self, response: str) -> Dict[str, Any]:
        """LLM 응답에서 JSON 추출"""
        # JSON 파싱
        try:
            # JSON 코드 블록 추출 (```json ... ``` 형식)
            import re
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', response)
            
            if json_match:
                json_str = json_match.group(1).strip()
                return json.loads(json_str)
            
            # JSON 블록이 없으면 전체 응답을 JSON으로 파싱 시도
            return json.loads(response)
            
        except Exception as e:
            logger.error(f"LLM 응답 파싱 오류: {str(e)}")
            return {"selected_agent_idx": None, "reason": f"LLM 응답 파싱 오류: {str(e)}"}


# 에이전트 생성 및 LLM 연결 예제
async def create_example_registry():
    """예제 에이전트 레지스트리 생성"""
    registry = AgentRegistry()
    await registry.initialize()
    
    # 1. 검색 에이전트 등록
    search_agent = AgentRegistryEntry(
        agent_id="internet_search_agent",
        name="인터넷 검색 에이전트",
        description="실시간 인터넷 검색을 수행하여 최신 정보를 제공하는 에이전트",
        agent_type=AgentType.INTERNET_SEARCH,
        bundle_type=BundleType.SELF_HOSTED,
        capabilities=[
            AgentCapability.INTERNET_SEARCH,
            AgentCapability.QA,
            AgentCapability.SUMMARIZATION
        ],
        examples=[
            {
                "input": "최신 AI 기술 트렌드는 무엇인가요?",
                "output": "최신 AI 기술 트렌드에는 1) 생성형 AI의 발전, 2) 멀티모달 모델의 등장, 3) AI 윤리와 규제 강화 등이 있습니다."
            },
            {
                "input": "2023년 노벨 물리학상 수상자는 누구인가요?",
                "output": "2023년 노벨 물리학상은 아토초 양자 물리학 분야의 선구적 실험 방법을 개발한 피에르 아고스티니, 페렌츠 크라우스, 앤 럴에게 수여되었습니다."
            }
        ],
        parameters={
            "search_engine": "default",
            "max_results": 5,
            "include_images": False
        }
    )
    registry.register_agent(search_agent)
    
    # 2. 텍스트 분석 에이전트 등록
    analysis_agent = AgentRegistryEntry(
        agent_id="text_analysis_agent",
        name="텍스트 분석 에이전트",
        description="텍스트 데이터를 분석하여 주요 주제, 감정, 요약 등을 제공하는 에이전트",
        agent_type=AgentType.ANALYSIS,
        bundle_type=BundleType.LLM_INTEGRATION,
        capabilities=[
            AgentCapability.TEXT_GENERATION,
            AgentCapability.SUMMARIZATION,
            AgentCapability.CLASSIFICATION
        ],
        examples=[
            {
                "input": "이 텍스트의 주요 주제를 분석해주세요: '기후 변화로 인한 해수면 상승은 전 세계 해안 도시에 위협이 되고 있습니다. 특히 방글라데시와 같은 저지대 국가들은 심각한 위험에 처해 있습니다.'",
                "output": "주요 주제: 기후 변화, 해수면 상승, 해안 도시 위협\n감정: 우려/경고\n영향 받는 지역: 저지대 국가, 특히 방글라데시"
            }
        ],
        parameters={
            "analysis_types": ["topic", "sentiment", "summary"],
            "language": "ko"
        }
    )
    registry.register_agent(analysis_agent)
    
    # 3. 코드 생성 에이전트 등록
    code_agent = AgentRegistryEntry(
        agent_id="code_generation_agent",
        name="코드 생성 에이전트",
        description="다양한 프로그래밍 언어로 코드를 생성하고 설명하는 에이전트",
        agent_type=AgentType.CUSTOM,
        bundle_type=BundleType.MANAGED_SOURCE,
        capabilities=[
            AgentCapability.CODE_GENERATION,
            AgentCapability.QA
        ],
        examples=[
            {
                "input": "파이썬으로 피보나치 수열을 계산하는 재귀 함수를 작성해주세요.",
                "output": "```python\ndef fibonacci(n):\n    if n <= 1:\n        return n\n    else:\n        return fibonacci(n-1) + fibonacci(n-2)\n\n# 테스트\nfor i in range(10):\n    print(fibonacci(i))\n```"
            }
        ],
        parameters={
            "supported_languages": ["python", "javascript", "java", "c++", "go"],
            "include_explanation": True,
            "include_tests": True
        }
    )
    registry.register_agent(code_agent)
    
    return registry


# LLM을 통한 에이전트 호출 예제
async def example_llm_agent_call(user_query: str):
    """LLM을 통한 에이전트 호출 예제"""
    # 레지스트리 생성
    registry = await create_example_registry()

    # LLM 클라이언트 설정 (실제 구현에서는 API 키 등 필요)
    try:
        from openai import AsyncOpenAI
        llm_client = AsyncOpenAI(api_key="your_api_key")
    except ImportError:
        llm_client = None
        logger.info("OpenAI 패키지가 설치되지 않았습니다. 더미 LLM 클라이언트를 사용합니다.")

    # 라우터 생성
    router = LLMAgentRouter(registry, llm_client)

    # 쿼리 라우팅 및 처리
    result = await router.route_query(user_query)

    # 결과 출력
    if result.type == AgentResponseType.ERROR:
        logger.error(f"오류: {result.message}")
        return None
    else:
        logger.info(f"선택된 에이전트: {result.metadata.get('selected_agent', {}).get('name', '알 수 없음')}")
        logger.info(f"선택 이유: {result.metadata.get('selected_agent', {}).get('reason', '알 수 없음')}")
        logger.info(f"응답: {result.message}")
        return result
        

# JSON 형식의 에이전트 정의 예시
AGENT_DEFINITION_JSON = """
{
  "agents": [
    {
      "agent_id": "internet_search_agent",
      "name": "인터넷 검색 에이전트",
      "description": "실시간 인터넷 검색을 수행하여 최신 정보를 제공하는 에이전트",
      "type": "INTERNET_SEARCH",
      "bundle_type": "self_hosted",
      "capabilities": ["internet_search", "question_answering", "summarization"],
      "examples": [
        {
          "input": "최신 AI 기술 트렌드는 무엇인가요?",
          "output": "최신 AI 기술 트렌드에는 1) 생성형 AI의 발전, 2) 멀티모달 모델의 등장, 3) AI 윤리와 규제 강화 등이 있습니다."
        }
      ],
      "parameters": {
        "search_engine": "default",
        "max_results": 5
      }
    },
    {
      "agent_id": "text_analysis_agent",
      "name": "텍스트 분석 에이전트",
      "description": "텍스트 데이터를 분석하여 주요 주제, 감정, 요약 등을 제공하는 에이전트",
      "type": "ANALYSIS",
      "bundle_type": "llm_integration",
      "capabilities": ["text_generation", "summarization", "classification"],
      "examples": [
        {
          "input": "이 텍스트의 감정을 분석해주세요: '오늘은 정말 행복한 하루였어요!'",
          "output": "감정 분석: 긍정적 (행복)"
        }
      ],
      "parameters": {
        "analysis_types": ["topic", "sentiment", "summary"]
      }
    }
  ]
}
"""

# LLM 호출 예시 응답
LLM_SELECTION_RESPONSE = """
사용자 질의를 분석한 결과, 인터넷 검색이 필요한 질문으로 판단됩니다.

```json
{
  "selected_agent_idx": 1,
  "reason": "사용자가 최신 정보를 요구하는 질의를 했기 때문에 인터넷 검색 에이전트가 가장 적합합니다.",
  "parameters": {
    "search_engine": "google",
    "max_results": 3
  }
}
```
"""

# 예제 실행
if __name__ == "__main__":
    # 비동기 함수 실행을 위한 헬퍼
    def run_async(coro):
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(coro)

    # 사용자 쿼리 예시
    user_query = "2023년 노벨상 수상자들은 누구인가요?"

    # 예제 실행
    result = run_async(example_llm_agent_call(user_query))

    # 레지스트리 JSON 출력 예시
    registry = run_async(create_example_registry())
    registry_json = registry.get_llm_registry_json()
    logger.info("\n에이전트 레지스트리 JSON:")
    logger.info(registry_json) 