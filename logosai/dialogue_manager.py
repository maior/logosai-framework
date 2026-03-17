"""
LogosAI 통합 대화 매니저

기존 Django 서버의 분산된 대화 시스템을 통합하여
에이전트 개발자가 쉽게 사용할 수 있는 인터페이스를 제공합니다.
"""

import asyncio
import uuid
from typing import Dict, Any, Optional, List, Callable, Union, AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from loguru import logger

# Django 서버 통합 (선택적)
try:
    import sys
    import os
    django_path = os.path.join(os.path.dirname(__file__), '../../logos_server')
    if django_path not in sys.path:
        sys.path.append(django_path)
    
    from app_agent.agent_dialogue_protocol import (
        AgentDialogueMessage, MessageType, AgentCapabilityDiscovery
    )
    from app_agent.interactive_parameter_collector import (
        InteractiveParameterCollector, CollectionStrategy, QueryAnalysis
    )
    from app_agent.query_analyzer import QueryAnalyzer
    from app_agent.query_transformer import QueryTransformer
    from app_agent.websocket_handler import WebSocketHandler
    
    DJANGO_INTEGRATION = True
    logger.info("Django dialogue system integration complete")

except ImportError as e:
    logger.debug(f"Django integration skipped, running in standalone mode: {e}")
    DJANGO_INTEGRATION = False
    
    # 독립 모드용 더미 클래스
    class AgentDialogueMessage:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
    
    class MessageType:
        CAPABILITY_INQUIRY = "capability_inquiry"
        PARAMETER_CHECK = "parameter_check"
        EXECUTION_REQUEST = "execution_request"
        STATUS_UPDATE = "status_update"
    
    class QueryAnalysis:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
    
    class CollectionStrategy:
        BATCH_ALL = "batch_all"
        ONE_BY_ONE = "one_by_one"
        PRIORITY_GROUPS = "priority_groups"
        SMART_GROUPING = "smart_grouping"


class DialogueState(Enum):
    """대화 상태"""
    IDLE = "idle"
    ANALYZING = "analyzing"
    COLLECTING_PARAMS = "collecting_params"
    EXECUTING = "executing"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class DialogueSession:
    """대화 세션"""
    session_id: str
    agent_id: str
    user_id: Optional[str] = None
    state: DialogueState = DialogueState.IDLE
    original_query: str = ""
    collected_parameters: Dict[str, Any] = field(default_factory=dict)
    analysis_result: Optional[Any] = None
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    websocket_handler: Optional[Callable] = None


class DialogueManager:
    """통합 대화 매니저"""
    
    def __init__(self):
        """대화 매니저 초기화"""
        self.active_sessions: Dict[str, DialogueSession] = {}
        self.capabilities_registry: Dict[str, Dict[str, Any]] = {}
        
        # Django 통합 컴포넌트
        if DJANGO_INTEGRATION:
            self.query_analyzer = QueryAnalyzer()
            self.query_transformer = QueryTransformer()
            self.parameter_collector = InteractiveParameterCollector()
            self.capability_discovery = AgentCapabilityDiscovery()
        else:
            self.query_analyzer = None
            self.query_transformer = None
            self.parameter_collector = None
            self.capability_discovery = None
        
        # 독립 모드 컴포넌트
        self._standalone_analyzers = {}
        
        logger.info("DialogueManager 초기화 완료")
    
    async def initialize(self):
        """매니저 초기화"""
        try:
            # Django 컴포넌트 초기화
            if DJANGO_INTEGRATION:
                # QueryAnalyzer 초기화는 보통 필요없음 (stateless)
                logger.info("Django 통합 컴포넌트 초기화 완료")
            else:
                await self._initialize_standalone_mode()
            
            return True
            
        except Exception as e:
            logger.error(f"DialogueManager 초기화 실패: {e}")
            return False
    
    async def _initialize_standalone_mode(self):
        """독립 모드 초기화"""
        logger.info("독립 모드로 초기화 중...")
        # 독립 모드용 간단한 쿼리 분석기 등 구현
        # 향후 확장 가능
    
    def register_agent_capabilities(self, 
                                   agent_id: str,
                                   capabilities: Dict[str, Any]):
        """에이전트 능력 등록
        
        Args:
            agent_id: 에이전트 ID
            capabilities: 능력 정보
        """
        self.capabilities_registry[agent_id] = {
            **capabilities,
            "registered_at": datetime.now(),
            "agent_id": agent_id
        }
        
        logger.info(f"에이전트 능력 등록: {agent_id}")
    
    async def start_dialogue(self,
                           agent_id: str,
                           query: str,
                           user_id: Optional[str] = None,
                           session_id: Optional[str] = None,
                           websocket_handler: Optional[Callable] = None,
                           progress_callback: Optional[Callable] = None) -> DialogueSession:
        """대화 시작
        
        Args:
            agent_id: 에이전트 ID
            query: 사용자 쿼리
            user_id: 사용자 ID
            session_id: 세션 ID (미제공시 자동 생성)
            websocket_handler: WebSocket 핸들러
            progress_callback: 진행 상황 콜백 함수
        
        Returns:
            DialogueSession: 대화 세션
        """
        if not session_id:
            session_id = f"dialogue_{uuid.uuid4().hex[:8]}"
        
        session = DialogueSession(
            session_id=session_id,
            agent_id=agent_id,
            user_id=user_id,
            original_query=query,
            websocket_handler=websocket_handler
        )
        
        # 진행 상황 콜백 저장
        if progress_callback:
            session.metadata["progress_callback"] = progress_callback
        
        self.active_sessions[session_id] = session
        
        logger.info(f"대화 시작: {session_id} -> {agent_id}")
        
        # 상태 업데이트 알림
        await self._notify_state_change(session, DialogueState.ANALYZING)
        
        return session
    
    async def analyze_query(self, session: DialogueSession) -> Optional[Any]:
        """쿼리 분석
        
        Args:
            session: 대화 세션
        
        Returns:
            QueryAnalysis: 분석 결과
        """
        try:
            session.state = DialogueState.ANALYZING
            await self._notify_state_change(session, DialogueState.ANALYZING)
            
            if DJANGO_INTEGRATION and self.query_analyzer:
                # Django QueryAnalyzer 사용
                analysis = await self.query_analyzer.analyze_query(
                    query=session.original_query,
                    agent_id=session.agent_id
                )
                
                session.analysis_result = analysis
                logger.info(f"쿼리 분석 완료: {session.session_id}")
                return analysis
                
            else:
                # 독립 모드 분석
                analysis = await self._standalone_query_analysis(session)
                session.analysis_result = analysis
                return analysis
                
        except Exception as e:
            logger.error(f"쿼리 분석 실패: {e}")
            session.state = DialogueState.ERROR
            await self._notify_state_change(session, DialogueState.ERROR)
            return None
    
    async def _standalone_query_analysis(self, session: DialogueSession) -> Any:
        """독립 모드 쿼리 분석"""
        # 간단한 키워드 기반 분석
        query = session.original_query.lower()
        
        # 에이전트 능력 정보 가져오기
        capabilities = self.capabilities_registry.get(session.agent_id, {})
        parameters = capabilities.get("parameters", {})
        
        # 누락된 필수 파라미터 찾기
        missing_params = []
        for param_name, param_info in parameters.items():
            if param_info.get("required", False):
                # 쿼리에서 파라미터 값을 찾을 수 없으면 누락
                if param_name.lower() not in query:
                    missing_params.append(param_name)
        
        # 모킹된 분석 결과
        return QueryAnalysis(
            complexity_score=0.5,
            missing_parameters=missing_params,
            requires_interaction=len(missing_params) > 0,
            confidence_score=0.8,
            extracted_entities={},
            intent="general",
            query=session.original_query
        )
    
    async def collect_parameters(self, session: DialogueSession) -> Dict[str, Any]:
        """파라미터 수집
        
        Args:
            session: 대화 세션
        
        Returns:
            Dict[str, Any]: 수집된 파라미터
        """
        try:
            if not session.analysis_result:
                logger.warning("분석 결과가 없어서 파라미터 수집 건너뜀")
                return {}
            
            missing_params = getattr(session.analysis_result, 'missing_parameters', [])
            if not missing_params:
                logger.info("누락된 파라미터가 없습니다")
                return session.collected_parameters
            
            session.state = DialogueState.COLLECTING_PARAMS
            await self._notify_state_change(session, DialogueState.COLLECTING_PARAMS)
            
            if DJANGO_INTEGRATION and self.parameter_collector and session.websocket_handler:
                # Django InteractiveParameterCollector 사용
                collected = await self.parameter_collector.collect_parameters(
                    session_id=session.session_id,
                    analysis=session.analysis_result,
                    strategy=CollectionStrategy.SMART_GROUPING,
                    websocket_handler=session.websocket_handler
                )
                
                session.collected_parameters.update(collected)
                logger.info(f"파라미터 수집 완료: {list(collected.keys())}")
                
            else:
                # 독립 모드 파라미터 수집
                collected = await self._standalone_parameter_collection(session)
                session.collected_parameters.update(collected)
            
            return session.collected_parameters
            
        except Exception as e:
            logger.error(f"파라미터 수집 실패: {e}")
            session.state = DialogueState.ERROR
            await self._notify_state_change(session, DialogueState.ERROR)
            return session.collected_parameters
    
    async def _standalone_parameter_collection(self, session: DialogueSession) -> Dict[str, Any]:
        """독립 모드 파라미터 수집"""
        # 간단한 기본값 제공
        collected = {}
        capabilities = self.capabilities_registry.get(session.agent_id, {})
        parameters = capabilities.get("parameters", {})
        
        missing_params = getattr(session.analysis_result, 'missing_parameters', [])
        
        for param_name in missing_params:
            param_info = parameters.get(param_name, {})
            default_value = param_info.get("default")
            
            if default_value is not None:
                collected[param_name] = default_value
                logger.info(f"기본값 사용: {param_name} = {default_value}")
            else:
                # 타입별 기본값
                param_type = param_info.get("type", "string")
                if param_type == "string":
                    collected[param_name] = ""
                elif param_type == "number":
                    collected[param_name] = 0
                elif param_type == "boolean":
                    collected[param_name] = False
                else:
                    collected[param_name] = None
        
        return collected
    
    async def transform_query(self, session: DialogueSession) -> Dict[str, Any]:
        """쿼리 변환
        
        Args:
            session: 대화 세션
        
        Returns:
            Dict[str, Any]: 변환된 파라미터
        """
        try:
            if DJANGO_INTEGRATION and self.query_transformer:
                # Django QueryTransformer 사용
                transformed = await self.query_transformer.transform_query_for_agent(
                    user_query=session.original_query,
                    agent_id=session.agent_id,
                    context=session.collected_parameters
                )
                
                logger.info(f"쿼리 변환 완료: {session.session_id}")
                return transformed
                
            else:
                # 독립 모드 변환
                return {
                    "query": session.original_query,
                    **session.collected_parameters
                }
                
        except Exception as e:
            logger.error(f"쿼리 변환 실패: {e}")
            return {"query": session.original_query}
    
    async def execute_conversation_flow(self,
                                      agent_id: str,
                                      query: str,
                                      user_id: Optional[str] = None,
                                      websocket_handler: Optional[Callable] = None) -> Dict[str, Any]:
        """전체 대화 플로우 실행
        
        Args:
            agent_id: 에이전트 ID
            query: 사용자 쿼리
            user_id: 사용자 ID
            websocket_handler: WebSocket 핸들러
        
        Returns:
            Dict[str, Any]: 실행 결과
        """
        session = None
        try:
            # 1. 대화 시작
            session = await self.start_dialogue(
                agent_id=agent_id,
                query=query,
                user_id=user_id,
                websocket_handler=websocket_handler
            )
            
            # 2. 쿼리 분석
            analysis = await self.analyze_query(session)
            if not analysis:
                raise Exception("쿼리 분석 실패")
            
            # 3. 파라미터 수집 (필요한 경우)
            if getattr(analysis, 'requires_interaction', False):
                await self.collect_parameters(session)
            
            # 4. 쿼리 변환
            transformed_params = await self.transform_query(session)
            
            # 5. 실행 준비 완료
            session.state = DialogueState.EXECUTING
            await self._notify_state_change(session, DialogueState.EXECUTING)
            
            result = {
                "session_id": session.session_id,
                "transformed_parameters": transformed_params,
                "analysis": analysis.__dict__ if hasattr(analysis, '__dict__') else analysis,
                "collected_parameters": session.collected_parameters,
                "ready_for_execution": True
            }
            
            # 6. 완료
            session.state = DialogueState.COMPLETED
            await self._notify_state_change(session, DialogueState.COMPLETED)
            
            logger.info(f"대화 플로우 완료: {session.session_id}")
            return result
            
        except Exception as e:
            logger.error(f"대화 플로우 실행 실패: {e}")
            if session:
                session.state = DialogueState.ERROR
                await self._notify_state_change(session, DialogueState.ERROR)
            
            return {
                "error": str(e),
                "session_id": session.session_id if session else None,
                "ready_for_execution": False
            }
    
    async def _notify_state_change(self, session: DialogueSession, new_state: DialogueState):
        """상태 변경 알림"""
        session.state = new_state
        session.updated_at = datetime.now()
        
        # 진행 상황 콜백 호출
        progress_callback = session.metadata.get("progress_callback")
        if progress_callback:
            try:
                await progress_callback({
                    "type": "state_change",
                    "session_id": session.session_id,
                    "state": new_state.value,
                    "message": f"대화 상태가 {new_state.value}로 변경되었습니다",
                    "timestamp": datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"진행 상황 콜백 실패: {e}")
        
        # WebSocket을 통한 실시간 알림
        if session.websocket_handler:
            try:
                await session.websocket_handler({
                    "type": "dialogue_state_change",
                    "session_id": session.session_id,
                    "state": new_state.value,
                    "timestamp": session.updated_at.isoformat()
                })
            except Exception as e:
                logger.warning(f"상태 변경 알림 실패: {e}")
        
        logger.debug(f"상태 변경: {session.session_id} -> {new_state.value}")
    
    def get_session(self, session_id: str) -> Optional[DialogueSession]:
        """세션 조회"""
        return self.active_sessions.get(session_id)
    
    def get_agent_capabilities(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """에이전트 능력 조회"""
        return self.capabilities_registry.get(agent_id)
    
    async def close_session(self, session_id: str):
        """세션 종료"""
        if session_id in self.active_sessions:
            session = self.active_sessions[session_id]
            session.state = DialogueState.COMPLETED
            await self._notify_state_change(session, DialogueState.COMPLETED)
            
            # 세션 정리 (메모리 절약을 위해 일정 시간 후)
            # 실제 구현에서는 백그라운드 태스크로 처리
            del self.active_sessions[session_id]
            
            logger.info(f"세션 종료: {session_id}")
    
    async def cleanup_expired_sessions(self, max_age_hours: int = 24):
        """만료된 세션 정리"""
        now = datetime.now()
        expired_sessions = []
        
        for session_id, session in self.active_sessions.items():
            age = now - session.created_at
            if age.total_seconds() > (max_age_hours * 3600):
                expired_sessions.append(session_id)
        
        for session_id in expired_sessions:
            await self.close_session(session_id)
        
        if expired_sessions:
            logger.info(f"만료된 세션 정리: {len(expired_sessions)}개")
    
    async def get_dialogue_stats(self) -> Dict[str, Any]:
        """대화 통계"""
        total_sessions = len(self.active_sessions)
        states = {}
        
        for session in self.active_sessions.values():
            state = session.state.value
            states[state] = states.get(state, 0) + 1
        
        return {
            "total_active_sessions": total_sessions,
            "sessions_by_state": states,
            "registered_agents": len(self.capabilities_registry),
            "django_integration": DJANGO_INTEGRATION
        }


# 싱글톤 인스턴스
_dialogue_manager_instance: Optional[DialogueManager] = None


def get_dialogue_manager() -> DialogueManager:
    """대화 매니저 싱글톤 인스턴스 반환"""
    global _dialogue_manager_instance
    if _dialogue_manager_instance is None:
        _dialogue_manager_instance = DialogueManager()
    return _dialogue_manager_instance


async def initialize_dialogue_system():
    """대화 시스템 전체 초기화"""
    manager = get_dialogue_manager()
    success = await manager.initialize()
    
    if success:
        logger.info("LogosAI 대화 시스템 초기화 완료")
        
        # 백그라운드 정리 태스크 시작
        asyncio.create_task(periodic_cleanup(manager))
    else:
        logger.error("LogosAI 대화 시스템 초기화 실패")
    
    return success


async def periodic_cleanup(manager: DialogueManager, interval_hours: int = 1):
    """주기적 세션 정리"""
    while True:
        try:
            await asyncio.sleep(interval_hours * 3600)
            await manager.cleanup_expired_sessions()
        except Exception as e:
            logger.error(f"주기적 정리 실패: {e}")


# 편의 함수들

async def quick_dialogue(agent_id: str, 
                        query: str,
                        websocket_handler: Optional[Callable] = None) -> Dict[str, Any]:
    """빠른 대화 실행"""
    manager = get_dialogue_manager()
    return await manager.execute_conversation_flow(
        agent_id=agent_id,
        query=query,
        websocket_handler=websocket_handler
    )


def register_agent(agent_id: str, capabilities: Dict[str, Any]):
    """에이전트 등록 편의 함수"""
    manager = get_dialogue_manager()
    manager.register_agent_capabilities(agent_id, capabilities)


# 사용 예제
if __name__ == "__main__":
    async def example():
        """사용 예제"""
        
        # 대화 시스템 초기화
        await initialize_dialogue_system()
        
        # 에이전트 능력 등록
        register_agent("weather_agent", {
            "parameters": {
                "location": {
                    "type": "string",
                    "required": True,
                    "description": "위치 정보"
                },
                "period": {
                    "type": "string", 
                    "required": False,
                    "default": "today",
                    "description": "기간"
                }
            },
            "visualization": {
                "supported": True,
                "chart_types": ["line", "bar"]
            }
        })
        
        # 대화 실행
        result = await quick_dialogue(
            agent_id="weather_agent",
            query="서울 날씨 알려줘"
        )

        logger.info(f"대화 결과: {result}")
    
    asyncio.run(example())