"""
LogosAI Agent Router

에러 내용을 기반으로 적절한 에이전트를 찾고 호출하는 라우팅 시스템입니다.
"""

from typing import Any, Dict, List, Optional, Union, Tuple
import re
import asyncio
from pathlib import Path
import importlib
import importlib.util
import inspect
import traceback
from loguru import logger
import os
import sys

from .agent import LogosAIAgent
from .agent_types import AgentResponseType, AgentResponse
from .config import AgentConfig


class AgentRouter:
    """
    에이전트 라우팅 시스템
    
    에러 내용을 분석하여 적절한 대체 에이전트를 찾고 처리를 위임합니다.
    """
    
    def __init__(self):
        self.agent_registry = {}  # 등록된 에이전트 목록
        self.error_patterns = {
            # PDF, DOC, DOCX 등 문서 관련 에러 패턴
            r"(?i)(pdf|doc|docx|ppt|pptx|xls|xlsx).*file": "document_agent",
            r"(?i)document.*process": "document_agent",
            r"(?i)cannot.*process.*(pdf|doc|docx|ppt|pptx)": "document_agent",
            r"(?i)cannot.*process.*document": "document_agent",
            r"(?i)cannot.*process.*content.*pdf": "document_agent",
            r"(?i)cannot.*process.*content.*msword": "document_agent",
            r"(?i)cannot.*process.*content.*openxml": "document_agent",
            r"(?i)content-type.*application": "document_agent",
            
            # 다른 에이전트 관련 에러 패턴들을 여기에 추가
            # 예: 이미지 처리, 오디오 처리 등
        }
        self.initialized = False
    
    async def initialize(self) -> bool:
        """라우터 초기화"""
        try:
            # 에이전트 목록 스캔 (examples/agents 디렉토리)
            await self._scan_agents()
            self.initialized = True
            logger.info(f"AgentRouter 초기화 완료: {len(self.agent_registry)}개 에이전트 등록됨")
            return True
        except Exception as e:
            logger.error(f"AgentRouter 초기화 실패: {str(e)}")
            return False
    
    async def _scan_agents(self) -> None:
        """
        사용 가능한 에이전트 스캔
        
        examples/agents 디렉토리에서 *_agent.py 파일들을 찾아
        에이전트 클래스 등록
        """
        try:
            # 현재 모듈 경로
            current_path = Path(__file__).parent
            logosai_root = current_path
            
            # examples/agents 디렉토리 경로
            agents_dir = current_path / "examples" / "agents"
            if not agents_dir.exists():
                logger.warning(f"에이전트 디렉토리가 존재하지 않습니다: {agents_dir}")
                # 상위 디렉토리 시도
                logosai_root = current_path.parent
                agents_dir = logosai_root / "examples" / "agents"
                if not agents_dir.exists():
                    logger.error(f"에이전트 디렉토리를 찾을 수 없습니다.")
                    return
            
            # 에이전트 파일 스캔 (*_agent.py)
            agent_files = list(agents_dir.glob("*_agent.py"))
            logger.info(f"발견된 에이전트 파일: {len(agent_files)}개")
            
            # 에이전트 디렉토리의 부모를 sys.path에 추가 (필요한 경우)
            if str(logosai_root) not in sys.path:
                logger.info(f"sys.path에 추가: {logosai_root}")
                sys.path.insert(0, str(logosai_root))
            
            for agent_file in agent_files:
                try:
                    # 파일명에서 에이전트 ID 추출 (파일명을 모듈 이름으로 사용)
                    agent_id = agent_file.stem  # 확장자 제외한 파일명
                    
                    # 모듈 이름 구성 (상대 경로 -> 절대 경로)
                    if str(logosai_root) == str(current_path):
                        # 현재 디렉토리가 logosai 패키지 루트인 경우
                        module_path = f"examples.agents.{agent_id}"
                    else:
                        # logosai 패키지의 상위 디렉토리인 경우
                        module_path = f"logosai.examples.agents.{agent_id}"
                    
                    # 에이전트 등록
                    self.agent_registry[agent_id] = {
                        "id": agent_id,
                        "module_path": module_path,
                        "file_path": str(agent_file),
                        "instance": None  # 지연 로딩을 위해 초기에는 None
                    }
                    
                    logger.info(f"에이전트 등록: {agent_id} (모듈: {module_path})")
                    
                except Exception as e:
                    logger.error(f"에이전트 등록 실패 ({agent_file.name}): {str(e)}")
        
        except Exception as e:
            logger.error(f"에이전트 스캔 중 오류: {str(e)}")
            raise
    
    async def _load_agent(self, agent_id: str) -> Optional[LogosAIAgent]:
        """
        에이전트 인스턴스 로드
        
        Args:
            agent_id: 로드할 에이전트 ID
            
        Returns:
            로드된 에이전트 인스턴스 또는 None
        """
        if agent_id not in self.agent_registry:
            logger.error(f"등록되지 않은 에이전트: {agent_id}")
            return None
        
        # 이미 로드된 인스턴스가 있으면 반환
        if self.agent_registry[agent_id]["instance"] is not None:
            return self.agent_registry[agent_id]["instance"]
        
        try:
            # 모듈 동적 로드
            module_path = self.agent_registry[agent_id]["module_path"]
            file_path = self.agent_registry[agent_id]["file_path"]
            
            # 모듈 로드 시도 (다양한 방법으로)
            try:
                # 방법 1: 일반적인 importlib 사용
                module = importlib.import_module(module_path)
                logger.info(f"모듈 로드 성공 (방법 1): {module_path}")
            except ModuleNotFoundError as e:
                logger.warning(f"모듈 로드 실패 (방법 1): {e}")
                
                # 방법 2: 파일 경로에서 직접 로드
                try:
                    # 파일 경로에서 디렉토리 경로 추출
                    module_dir = os.path.dirname(file_path)
                    module_name = os.path.basename(file_path).replace('.py', '')
                    
                    # sys.path에 모듈 디렉토리 추가
                    if module_dir not in sys.path:
                        sys.path.insert(0, module_dir)
                    
                    # 파일에서 직접 모듈 로드
                    spec = importlib.util.spec_from_file_location(module_name, file_path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    logger.info(f"모듈 로드 성공 (방법 2): {file_path}")
                except Exception as direct_load_error:
                    logger.error(f"모듈 로드 실패 (방법 2): {direct_load_error}")
                    
                    # 방법 3: 패키지 경로 조정 시도
                    try:
                        # 상위 디렉토리를 sys.path에 추가
                        parent_dir = os.path.dirname(os.path.dirname(file_path))
                        if parent_dir not in sys.path:
                            sys.path.insert(0, parent_dir)
                        
                        # 상위 디렉토리를 기준으로 모듈 경로 재구성
                        adjusted_module_path = f"agents.{module_name}"
                        module = importlib.import_module(adjusted_module_path)
                        logger.info(f"모듈 로드 성공 (방법 3): {adjusted_module_path}")
                    except Exception as adjusted_load_error:
                        logger.error(f"모듈 로드 실패 (방법 3): {adjusted_load_error}")
                        raise Exception(f"모든 모듈 로드 방법 실패: {str(e)}, {str(direct_load_error)}, {str(adjusted_load_error)}")
            
            # 에이전트 클래스 찾기
            agent_class = None
            for name, obj in inspect.getmembers(module):
                if (inspect.isclass(obj) and 
                    issubclass(obj, LogosAIAgent) and 
                    obj.__name__.lower().endswith('agent')):
                    agent_class = obj
                    break
            
            if not agent_class:
                logger.error(f"에이전트 클래스를 찾을 수 없음: {module_path}")
                return None
            
            # 에이전트 인스턴스 생성 및 초기화
            # create_default 메서드가 있으면 사용
            if hasattr(agent_class, 'create_default'):
                agent = agent_class.create_default()
            else:
                agent = agent_class()
            
            # 에이전트 초기화
            await agent.initialize()
            
            # 레지스트리에 인스턴스 저장
            self.agent_registry[agent_id]["instance"] = agent
            
            logger.info(f"에이전트 로드 성공: {agent_id}")
            return agent
            
        except Exception as e:
            logger.error(f"에이전트 로드 실패 ({agent_id}): {str(e)}")
            logger.error(traceback.format_exc())
            return None
    
    async def find_agent_for_error(self, error_message: str) -> Optional[str]:
        """
        에러 메시지를 분석하여 적절한 에이전트 ID 찾기
        
        Args:
            error_message: 에러 메시지
            
        Returns:
            적절한 에이전트 ID 또는 None
        """
        for pattern, agent_id in self.error_patterns.items():
            if re.search(pattern, error_message):
                logger.info(f"에러 메시지와 일치하는 패턴 발견: {pattern} -> {agent_id}")
                
                # 에이전트가 등록되어 있는지 확인
                if agent_id in self.agent_registry:
                    return agent_id
                else:
                    logger.warning(f"패턴과 일치하는 에이전트가 등록되지 않음: {agent_id}")
        
        logger.info(f"에러 메시지와 일치하는 패턴 없음: {error_message[:100]}...")
        return None
    
    async def route_error(self, error_message: str, original_request: Any) -> Tuple[bool, Optional[AgentResponse], Optional[str]]:
        """
        에러를 적절한 에이전트로 라우팅
        
        Args:
            error_message: 에러 메시지
            original_request: 원본 요청 데이터
            
        Returns:
            (성공 여부, 에이전트 응답, 에이전트 ID)
        """
        if not self.initialized:
            success = await self.initialize()
            if not success:
                logger.error("AgentRouter 초기화 실패")
                return False, None, None
        
        # 에러 메시지로 적절한 에이전트 찾기
        agent_id = await self.find_agent_for_error(error_message)
        if not agent_id:
            logger.warning(f"적절한 대체 에이전트를 찾을 수 없음")
            return False, None, None
        
        # 에이전트 로드
        agent = await self._load_agent(agent_id)
        if not agent:
            logger.error(f"에이전트 로드 실패: {agent_id}")
            return False, None, None
        
        try:
            # 에이전트로 요청 처리
            logger.info(f"요청을 {agent_id}로 라우팅")
            response = await agent.process(original_request)
            
            return True, response, agent_id
            
        except Exception as e:
            logger.error(f"대체 에이전트 처리 실패 ({agent_id}): {str(e)}")
            return False, None, agent_id
    
    async def process_with_fallback(self, 
                                   primary_agent: LogosAIAgent, 
                                   request: Any,
                                   use_error_routing: bool = True) -> AgentResponse:
        """
        주 에이전트로 처리하고, 실패 시 대체 에이전트로 라우팅
        
        Args:
            primary_agent: 주 에이전트 인스턴스
            request: 처리할 요청
            use_error_routing: 에러 라우팅 사용 여부
            
        Returns:
            처리 결과
        """
        try:
            # 주 에이전트로 처리 시도
            response = await primary_agent.process(request)
            
            # 오류 응답인 경우 에러 라우팅 시도
            if use_error_routing and response.type == AgentResponseType.ERROR:
                error_message = response.content.get("error", "")
                if error_message:
                    logger.info(f"주 에이전트에서 오류 발생, 에러 라우팅 시도: {error_message}")
                    success, fallback_response, agent_id = await self.route_error(error_message, request)
                    
                    if success and fallback_response:
                        logger.info(f"대체 에이전트({agent_id})로 성공적으로 처리됨")
                        
                        # 메타데이터에 라우팅 정보 추가
                        if fallback_response.metadata is None:
                            fallback_response.metadata = {}
                        fallback_response.metadata["routed_from"] = primary_agent.__class__.__name__
                        fallback_response.metadata["routed_to"] = agent_id
                        fallback_response.metadata["original_error"] = error_message
                        
                        return fallback_response
            
            # 주 에이전트 처리 결과 반환
            return response
            
        except Exception as e:
            error_message = str(e)
            logger.error(f"주 에이전트 처리 중 예외 발생: {error_message}")
            
            if use_error_routing:
                # 에러 라우팅 시도
                success, fallback_response, agent_id = await self.route_error(error_message, request)
                
                if success and fallback_response:
                    logger.info(f"대체 에이전트({agent_id})로 성공적으로 처리됨")
                    
                    # 메타데이터에 라우팅 정보 추가
                    if fallback_response.metadata is None:
                        fallback_response.metadata = {}
                    fallback_response.metadata["routed_from"] = primary_agent.__class__.__name__
                    fallback_response.metadata["routed_to"] = agent_id
                    fallback_response.metadata["original_error"] = error_message
                    
                    return fallback_response
            
            # 오류 응답 반환
            return AgentResponse(
                type=AgentResponseType.ERROR,
                content={
                    "error": f"처리 중 오류: {error_message}",
                    "message": f"처리 중 오류가 발생했습니다."
                },
                metadata={
                    "error_type": type(e).__name__,
                    "agent": primary_agent.__class__.__name__
                }
            )


# 싱글톤 인스턴스
_router_instance = None

def get_router() -> AgentRouter:
    """AgentRouter 싱글톤 인스턴스 반환"""
    global _router_instance
    if _router_instance is None:
        _router_instance = AgentRouter()
    return _router_instance


async def route_error(error_message: str, original_request: Any) -> Tuple[bool, Optional[AgentResponse], Optional[str]]:
    """
    에러를 적절한 에이전트로 라우팅 (편의 함수)
    
    Args:
        error_message: 에러 메시지
        original_request: 원본 요청 데이터
        
    Returns:
        (성공 여부, 에이전트 응답, 에이전트 ID)
    """
    router = get_router()
    return await router.route_error(error_message, original_request)


async def process_with_fallback(primary_agent: LogosAIAgent, 
                               request: Any,
                               use_error_routing: bool = True) -> AgentResponse:
    """
    주 에이전트로 처리하고, 실패 시 대체 에이전트로 라우팅 (편의 함수)
    
    Args:
        primary_agent: 주 에이전트 인스턴스
        request: 처리할 요청
        use_error_routing: 에러 라우팅 사용 여부
        
    Returns:
        처리 결과
    """
    router = get_router()
    return await router.process_with_fallback(primary_agent, request, use_error_routing) 