"""
LogosAI Agent Market 모듈

에이전트 마켓플레이스를 통해 다양한 AI 에이전트를 검색하고 활용할 수 있는 기능을 제공합니다.
"""

import os
import json
import logging
import asyncio
from typing import Dict, List, Any, Optional, Union
from uuid import uuid4

# 로깅 설정
logger = logging.getLogger(__name__)

# 기본 에이전트 마켓 엔드포인트
DEFAULT_MARKET_ENDPOINT = "https://market.logosai.com"

class AgentInstance:
    """에이전트 인스턴스 정보를 담는 클래스"""
    
    def __init__(self, id: str, agent_id: str, endpoint: str, metadata: Optional[Dict[str, Any]] = None):
        self.id = id
        self.agent_id = agent_id
        self.endpoint = endpoint
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """인스턴스 정보를 딕셔너리로 변환"""
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "endpoint": self.endpoint,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentInstance':
        """딕셔너리로부터 인스턴스 객체 생성"""
        return cls(
            id=data["id"],
            agent_id=data["agent_id"],
            endpoint=data["endpoint"],
            metadata=data.get("metadata", {})
        )


class AgentMarket:
    """Agent Market 클래스
    
    다양한 LogosAI 에이전트를 검색하고 사용할 수 있는 마켓플레이스 인터페이스입니다.
    """
    
    def __init__(self, endpoint: str = DEFAULT_MARKET_ENDPOINT, api_key: Optional[str] = None):
        """
        Agent Market 초기화
        
        Args:
            endpoint: Agent Market API 엔드포인트
            api_key: API 키 (선택 사항)
        """
        self.endpoint = endpoint
        self.api_key = api_key or os.environ.get("LOGOSAI_API_KEY")
        self._active_instances = {}
        
        # HTTP 세션 (지연 초기화)
        self._session = None
    
    async def _ensure_session(self):
        """HTTP 세션이 초기화되었는지 확인"""
        if self._session is None:
            try:
                import aiohttp
                headers = {}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                self._session = aiohttp.ClientSession(headers=headers)
            except ImportError:
                raise ImportError("aiohttp 라이브러리를 설치해야 합니다: pip install aiohttp")
        return self._session
    
    async def close(self):
        """리소스 정리"""
        if self._session:
            await self._session.close()
            self._session = None
    
    async def list_agents(self, category: Optional[str] = None, query: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        사용 가능한 에이전트 목록 조회
        
        Args:
            category: 에이전트 카테고리 필터 (선택 사항)
            query: 검색 쿼리 (선택 사항)
            
        Returns:
            에이전트 목록
        """
        session = await self._ensure_session()
        
        params = {}
        if category:
            params["category"] = category
        if query:
            params["query"] = query
        
        try:
            async with session.get(f"{self.endpoint}/agents", params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("agents", [])
                else:
                    error_text = await response.text()
                    logger.error(f"에이전트 목록 조회 실패: {response.status} - {error_text}")
                    return []
        except Exception as e:
            logger.error(f"에이전트 목록 조회 중 오류: {str(e)}")
            return []
    
    async def get_agent_info(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        특정 에이전트의 상세 정보 조회
        
        Args:
            agent_id: 에이전트 ID
            
        Returns:
            에이전트 상세 정보 또는 None
        """
        session = await self._ensure_session()
        
        try:
            async with session.get(f"{self.endpoint}/agents/{agent_id}") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"에이전트 정보 조회 실패: {response.status} - {error_text}")
                    return None
        except Exception as e:
            logger.error(f"에이전트 정보 조회 중 오류: {str(e)}")
            return None
    
    async def provision_agent(self, agent_id: str, config: Optional[Dict[str, Any]] = None) -> Optional[AgentInstance]:
        """
        에이전트 인스턴스 프로비저닝
        
        Args:
            agent_id: 에이전트 ID
            config: 에이전트 구성 파라미터 (선택 사항)
            
        Returns:
            에이전트 인스턴스 정보 또는 None
        """
        session = await self._ensure_session()
        
        try:
            data = {"agent_id": agent_id}
            if config:
                data["config"] = config
                
            async with session.post(f"{self.endpoint}/provision", json=data) as response:
                if response.status == 200:
                    instance_data = await response.json()
                    instance = AgentInstance.from_dict(instance_data)
                    
                    # 활성 인스턴스 추적
                    self._active_instances[instance.id] = instance
                    return instance
                else:
                    error_text = await response.text()
                    logger.error(f"에이전트 프로비저닝 실패: {response.status} - {error_text}")
                    return None
        except Exception as e:
            logger.error(f"에이전트 프로비저닝 중 오류: {str(e)}")
            return None
    
    async def release_agent(self, instance_id: str) -> bool:
        """
        에이전트 인스턴스 해제
        
        Args:
            instance_id: 인스턴스 ID
            
        Returns:
            성공 여부
        """
        session = await self._ensure_session()
        
        try:
            async with session.post(f"{self.endpoint}/release/{instance_id}") as response:
                success = response.status == 200
                if success:
                    # 활성 인스턴스에서 제거
                    if instance_id in self._active_instances:
                        del self._active_instances[instance_id]
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"에이전트 해제 실패: {response.status} - {error_text}")
                    return False
        except Exception as e:
            logger.error(f"에이전트 해제 중 오류: {str(e)}")
            return False
    
    def __del__(self):
        """소멸자"""
        # 비동기 세션 정리
        if self._session:
            asyncio.create_task(self.close())


class AgentMarketTools:
    """LLM 도구(Tool) 형태로 에이전트를 사용할 수 있는 유틸리티 클래스"""
    
    def __init__(self, market_endpoint: str = DEFAULT_MARKET_ENDPOINT, api_key: Optional[str] = None):
        """
        Agent Market Tools 초기화
        
        Args:
            market_endpoint: Agent Market API 엔드포인트
            api_key: API 키 (선택 사항)
        """
        self.market = AgentMarket(endpoint=market_endpoint, api_key=api_key)
        self._tools_cache = {}
        self._instances = {}
    
    def get_openai_tools(self, agent_ids: List[str]) -> List[Dict[str, Any]]:
        """
        OpenAI 호환 도구 정의 가져오기
        
        Args:
            agent_ids: 도구로 사용할 에이전트 ID 목록
            
        Returns:
            OpenAI 호환 도구 정의 목록
        """
        tools = []
        
        for agent_id in agent_ids:
            # 캐시된 도구 정의 확인
            if agent_id in self._tools_cache:
                tools.append(self._tools_cache[agent_id])
                continue
            
            # 도구 정의 생성
            tool = {
                "type": "function",
                "function": {
                    "name": f"use_{agent_id}",
                    "description": f"{agent_id} 에이전트를 사용하여 작업을 수행합니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "에이전트에 전달할 쿼리 또는 명령"
                            },
                            "options": {
                                "type": "object",
                                "description": "추가 옵션 (선택 사항)"
                            }
                        },
                        "required": ["query"]
                    }
                }
            }
            
            # 도구 캐시에 저장
            self._tools_cache[agent_id] = tool
            tools.append(tool)
        
        return tools
    
    async def execute_tool(self, tool_name: str, tool_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        도구 실행
        
        Args:
            tool_name: 도구 이름 (use_로 시작)
            tool_params: 도구 파라미터
            
        Returns:
            실행 결과
        """
        # 도구 이름에서 에이전트 ID 추출
        if not tool_name.startswith("use_"):
            return {"error": "잘못된 도구 이름 형식입니다."}
            
        agent_id = tool_name[4:]  # "use_" 제외
        query = tool_params.get("query")
        options = tool_params.get("options", {})
        
        if not query:
            return {"error": "쿼리가 제공되지 않았습니다."}
        
        try:
            # 에이전트 인스턴스 가져오기 (캐시 확인)
            instance = None
            instance_key = f"{agent_id}_{json.dumps(options)}"
            
            if instance_key in self._instances:
                instance = self._instances[instance_key]
            else:
                # 새 인스턴스 프로비저닝
                instance = await self.market.provision_agent(agent_id, options)
                if instance:
                    self._instances[instance_key] = instance
            
            if not instance:
                return {"error": f"{agent_id} 에이전트를 프로비저닝할 수 없습니다."}
            
            # 에이전트 실행
            from ..acp import ACPClient
            client = ACPClient(endpoint=instance.endpoint)
            
            try:
                result = await client.query(query)
                return result
            finally:
                await client.close()
                
        except Exception as e:
            logger.error(f"도구 실행 중 오류: {str(e)}")
            return {"error": f"도구 실행 중 오류가 발생했습니다: {str(e)}"}
    
    async def close(self):
        """리소스 정리"""
        # 모든 인스턴스 해제
        for instance_key, instance in self._instances.items():
            try:
                await self.market.release_agent(instance.id)
            except Exception:
                pass
        
        self._instances.clear()
        await self.market.close()
    
    def __del__(self):
        """소멸자"""
        asyncio.create_task(self.close())


# 모듈 수준의 인스턴스
_default_market = None

def get_market(endpoint: str = DEFAULT_MARKET_ENDPOINT, api_key: Optional[str] = None) -> AgentMarket:
    """
    기본 Agent Market 인스턴스 가져오기
    
    Args:
        endpoint: Agent Market API 엔드포인트
        api_key: API 키 (선택 사항)
        
    Returns:
        AgentMarket 인스턴스
    """
    global _default_market
    if _default_market is None:
        _default_market = AgentMarket(endpoint=endpoint, api_key=api_key)
    return _default_market 