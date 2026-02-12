"""
LogosAI 워크플로우 매니저 모듈

이 모듈은 LogosAI 에이전트들 간의 워크플로우를 관리하기 위한 기능을 제공합니다.
"""

import os
import sys
import asyncio
import json
import time
import uuid
import logging
from datetime import datetime
from typing import Dict, List, Any, Callable, Optional, Set, Union, TypeVar

# 로거 설정
logger = logging.getLogger(__name__)

# LogosAI 임포트
from ..agent import LogosAIAgent
from ..types import AgentType, AgentResponseType, AgentResponse
from ..message_bus import MessageBus, Message
from ..utils.config_loader import get_config_loader, load_config, get_config_value, set_config_value

# 워크플로우 그래프 임포트
from .workflow_graph import WorkflowGraph, create_workflow_graph

# 싱글톤 인스턴스
_workflow_manager_instance = None

# 타입 정의
State = TypeVar('State', bound=Dict[str, Any])

class WorkflowManager:
    """워크플로우 매니저 클래스"""
    
    def __init__(self, config_dir: str = None):
        """워크플로우 매니저를 초기화합니다.
        
        Args:
            config_dir (str, optional): 설정 파일이 있는 디렉토리 경로. 기본값은 None.
        """
        # 설정 디렉토리 설정
        self._config_dir = config_dir
        if not self._config_dir:
            # 패키지 설정 디렉토리 기본 경로
            package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self._config_dir = os.path.join(package_dir, "config")
            
            # 환경 변수로 설정 디렉토리 지정 가능
            env_config_dir = os.environ.get("LOGOSAI_WORKFLOW_CONFIG_DIR")
            if env_config_dir:
                self._config_dir = env_config_dir
        
        # 워크플로우 상태 초기화
        self._state = {}
        self._history = []
        
        # 워크플로우 메트릭스 초기화
        self._active_workflows = set()
        self._completed_workflows = set()
        self._failed_workflows = set()
        self._workflow_metrics = {
            "total_workflows": 0,
            "active_workflows": 0,
            "completed_workflows": 0,
            "failed_workflows": 0,
            "total_nodes": 0,
            "total_edges": 0,
            "avg_completion_time": 0,
            "errors": []
        }
        
        # 초기화 플래그
        self._initialized = False
        self._initializing = False
        self._init_completed_event = None
        
        # 에이전트 및 미들웨어 컨테이너
        self.agents = {}
        self.middlewares = []
        self.node_middlewares = {}
        self.global_middlewares = []
        
        # 이벤트 핸들러 초기화
        self.event_handlers = {
            "workflow_start": [],
            "workflow_end": [],
            "node_entry": [],
            "node_exit": [],
            "edge_traversal": [],
            "error": []
        }
        
        # 워크플로우 그래프는 초기화 후 생성
        self.workflow = None
        
        # 메시지 버스 인스턴스
        self.message_bus = None
        
        # 설정 로드
        self.load_configs()
        
        # 초기화 재시도 설정
        self.max_retries = 3
        self.retry_delay = 1
        
        if self.workflow_config.get("exists", False):
            self.max_retries = self.workflow_config.get("workflow", {}).get("settings", {}).get("max_retries", 3)
            self.retry_delay = self.workflow_config.get("workflow", {}).get("settings", {}).get("retry_delay_seconds", 1)
        
        logger.info("워크플로우 매니저 생성 완료 - 초기화는 별도로 수행해야 합니다.")
    
    def load_configs(self):
        """설정 파일 로드"""
        # 설정 로드
        self.state_config = self._load_config("workflow_state")
        self.nodes_config = self._load_config("workflow_nodes")
        self.routing_config = self._load_config("workflow_routing")
        self.workflow_config = self._load_config("workflow_config")
        
        # 에이전트 설정 로드
        self.agents_config = self._load_config("agents")
        
        # 설정 파일 로드 결과 로깅
        logger.info(f"State 설정 파일: {self.state_config.get('file_path', 'None')}")
        logger.info(f"Nodes 설정 파일: {self.nodes_config.get('file_path', 'None')}")
        logger.info(f"Routing 설정 파일: {self.routing_config.get('file_path', 'None')}")
        logger.info(f"Workflow 설정 파일: {self.workflow_config.get('file_path', 'None')}")
        
        # 필수 설정 파일 확인
        if not self.workflow_config.get("exists", False):
            logger.error("필수 설정 파일(workflow_config)이 로드되지 않았습니다.")
        
        # 초기 상태 설정
        if self.state_config.get("exists", False):
            self.initial_state = self.state_config.get("state", {}).get("initial", {}).copy()
        else:
            self.initial_state = {}
    
    def _load_config(self, config_name: str) -> dict:
        """설정 파일 로드
        
        Args:
            config_name: 설정 파일 이름
            
        Returns:
            설정 데이터
        """
        config_file = f"{config_name}.json"
        config_path = os.path.join(self._config_dir, config_file)
        
        # 파일 존재 확인
        exists = os.path.exists(config_path)
        
        if not exists:
            logger.warning(f"설정 파일을 찾을 수 없습니다: {config_path}")
            return {"exists": False, "file_path": config_path}
        
        try:
            # JSON 파일 로드
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
                
            # 파일 경로 추가
            config["exists"] = True
            config["file_path"] = config_path
            
            logger.info(f"설정 파일 로드 성공: {config_path}")
            return config
            
        except Exception as e:
            logger.error(f"설정 파일 로드 중 오류: {str(e)} ({config_path})")
            return {"exists": False, "file_path": config_path, "error": str(e)}
    
    def get_active_workflow_count(self) -> int:
        """활성 워크플로우 수 반환"""
        return len(self._active_workflows)
        
    def get_completed_workflow_count(self) -> int:
        """완료된 워크플로우 수 반환"""
        return len(self._completed_workflows)
        
    def get_failed_workflow_count(self) -> int:
        """실패한 워크플로우 수 반환"""
        return len(self._failed_workflows)
        
    def get_total_workflow_count(self) -> int:
        """전체 워크플로우 수 반환"""
        return self._workflow_metrics["total_workflows"]
        
    def get_total_node_count(self) -> int:
        """전체 노드 수 반환"""
        return self._workflow_metrics["total_nodes"]
        
    def get_total_edge_count(self) -> int:
        """전체 엣지 수 반환"""
        return self._workflow_metrics["total_edges"]
        
    def get_average_completion_time(self) -> float:
        """평균 완료 시간 반환"""
        return self._workflow_metrics["avg_completion_time"]
        
    def get_error_count(self) -> int:
        """오류 수 반환"""
        return len(self._workflow_metrics["errors"])
        
    def get_workflow_metrics(self) -> Dict[str, Any]:
        """워크플로우 메트릭 반환"""
        return self._workflow_metrics.copy()
    
    async def initialize(self, message_bus: Optional[MessageBus] = None) -> bool:
        """워크플로우 매니저 초기화
        
        Args:
            message_bus (Optional[MessageBus]): 메시지 버스 인스턴스
            
        Returns:
            bool: 초기화 성공 여부
        """
        # 이미 초기화 중이면 완료될 때까지 대기
        if self._initializing:
            logger.info("워크플로우 매니저가 이미 초기화 중입니다. 완료될 때까지 대기합니다.")
            if self._init_completed_event:
                await self._init_completed_event.wait()
            return self._initialized
        
        # 이미 초기화되었으면 바로 반환
        if self._initialized:
            logger.info("워크플로우 매니저가 이미 초기화되었습니다.")
            return True
        
        # 초기화 플래그 설정
        self._initializing = True
        self._init_completed_event = asyncio.Event()
        
        try:
            # 메시지 버스 설정
            if message_bus:
                self.message_bus = message_bus
                logger.info("외부 메시지 버스 사용")
            else:
                # 메시지 버스 생성
                self.message_bus = MessageBus()
                await self.message_bus.start()
                logger.info("내부 메시지 버스 생성 및 시작")
            
            # 에이전트 초기화
            await self._initialize_agents()
            
            # 워크플로우 그래프 생성
            await self._create_workflow_graph()
            
            # 기본 이벤트 핸들러 등록
            self._register_default_event_handlers()
            
            # 기본 미들웨어 등록
            self._register_default_middlewares()
            
            # 초기화 성공
            self._initialized = True
            logger.info("워크플로우 매니저 초기화 성공")
            
            return True
            
        except Exception as e:
            logger.error(f"워크플로우 매니저 초기화 중 오류: {str(e)}")
            self._initialized = False
            return False
            
        finally:
            # 초기화 플래그 해제
            self._initializing = False
            if self._init_completed_event:
                self._init_completed_event.set()
    
    async def is_initialized(self) -> bool:
        """워크플로우 매니저 초기화 상태 확인
        
        Returns:
            bool: 초기화 상태
        """
        return self._initialized
    
    async def shutdown(self) -> None:
        """워크플로우 매니저 종료"""
        logger.info("워크플로우 매니저 종료 중...")
        
        # 내부 메시지 버스 정리
        if self.message_bus and hasattr(self.message_bus, 'stop'):
            try:
                await self.message_bus.stop()
                logger.info("메시지 버스 종료 완료")
            except Exception as e:
                logger.error(f"메시지 버스 종료 중 오류: {str(e)}")
        
        # 에이전트 정리
        for agent_id, agent in self.agents.items():
            if hasattr(agent, 'close'):
                try:
                    await agent.close()
                    logger.info(f"에이전트 '{agent_id}' 종료 완료")
                except Exception as e:
                    logger.error(f"에이전트 '{agent_id}' 종료 중 오류: {str(e)}")
        
        # 초기화 상태 해제
        self._initialized = False
        logger.info("워크플로우 매니저 종료 완료")
    
    async def _initialize_agents(self) -> None:
        """에이전트 초기화"""
        if not self.agents_config.get("exists", False):
            logger.warning("에이전트 설정 파일이 없습니다. 에이전트를 초기화할 수 없습니다.")
            return
        
        agents_config = self.agents_config.get("agents", {})
        for agent_id, config in agents_config.items():
            try:
                # 에이전트 로드
                await self.load_agent(agent_id)
            except Exception as e:
                logger.error(f"에이전트 '{agent_id}' 초기화 중 오류: {str(e)}")
    
    async def load_agent(self, agent_id: str) -> bool:
        """에이전트 로드
        
        Args:
            agent_id (str): 에이전트 ID
            
        Returns:
            bool: 로드 성공 여부
        """
        # 에이전트가 이미 로드되었는지 확인
        if agent_id in self.agents:
            logger.info(f"에이전트 '{agent_id}'는 이미 로드되었습니다.")
            return True
        
        # 에이전트 설정이 있는지 확인
        if not self.agents_config.get("exists", False):
            logger.error(f"에이전트 설정 파일이 없습니다. 에이전트 '{agent_id}'를 로드할 수 없습니다.")
            return False
        
        # 에이전트 설정 가져오기
        agents_config = self.agents_config.get("agents", {})
        if agent_id not in agents_config:
            logger.error(f"에이전트 '{agent_id}'의 설정이 없습니다.")
            return False
        
        agent_config = agents_config[agent_id]
        
        try:
            # 에이전트 타입 가져오기
            agent_type = agent_config.get("type")
            if not agent_type:
                logger.error(f"에이전트 '{agent_id}'의 타입이 정의되지 않았습니다.")
                return False
            
            # 에이전트 생성 방법에 따라 처리
            if agent_type == "logos_sdk":
                # LogosAI SDK 에이전트 생성
                agent_class = agent_config.get("class")
                agent_module = agent_config.get("module")
                
                if not agent_class or not agent_module:
                    logger.error(f"에이전트 '{agent_id}'의 클래스 또는 모듈이 정의되지 않았습니다.")
                    return False
                
                # 모듈 동적 로드
                try:
                    module = __import__(agent_module, fromlist=[agent_class])
                    agent_cls = getattr(module, agent_class)
                    
                    # 에이전트 생성
                    agent = agent_cls()
                    
                    # 메시지 버스 설정
                    if hasattr(agent, 'set_message_bus'):
                        agent.set_message_bus(self.message_bus)
                    
                    # 에이전트 초기화
                    if hasattr(agent, 'initialize'):
                        await agent.initialize()
                    
                    # 에이전트 등록
                    self.agents[agent_id] = agent
                    logger.info(f"에이전트 '{agent_id}' 로드 성공 (LogosAI SDK)")
                    
                    return True
                    
                except Exception as e:
                    logger.error(f"에이전트 '{agent_id}' 로드 중 오류: {str(e)}")
                    return False
            
            elif agent_type == "function":
                # 함수 기반 에이전트 생성
                handler_module = agent_config.get("module")
                handler_function = agent_config.get("function")
                
                if not handler_module or not handler_function:
                    logger.error(f"에이전트 '{agent_id}'의 모듈 또는 함수가 정의되지 않았습니다.")
                    return False
                
                # 모듈 동적 로드
                try:
                    module = __import__(handler_module, fromlist=[handler_function])
                    handler = getattr(module, handler_function)
                    
                    # 에이전트 등록 (함수를 그대로 저장)
                    self.agents[agent_id] = handler
                    logger.info(f"에이전트 '{agent_id}' 로드 성공 (함수)")
                    
                    return True
                    
                except Exception as e:
                    logger.error(f"에이전트 '{agent_id}' 로드 중 오류: {str(e)}")
                    return False
            
            else:
                logger.error(f"에이전트 '{agent_id}'의 타입 '{agent_type}'이 지원되지 않습니다.")
                return False
            
        except Exception as e:
            logger.error(f"에이전트 '{agent_id}' 로드 중 오류: {str(e)}")
            return False
    
    async def unload_agent(self, agent_id: str) -> bool:
        """에이전트 언로드
        
        Args:
            agent_id (str): 에이전트 ID
            
        Returns:
            bool: 언로드 성공 여부
        """
        if agent_id not in self.agents:
            logger.warning(f"에이전트 '{agent_id}'는 로드되지 않았습니다.")
            return False
        
        try:
            # 에이전트 정리
            agent = self.agents[agent_id]
            if hasattr(agent, 'close'):
                await agent.close()
            
            # 에이전트 제거
            del self.agents[agent_id]
            
            logger.info(f"에이전트 '{agent_id}' 언로드 성공")
            return True
            
        except Exception as e:
            logger.error(f"에이전트 '{agent_id}' 언로드 중 오류: {str(e)}")
            return False
    
    def _register_default_middlewares(self):
        """기본 미들웨어 등록"""
        # 상태 검증 미들웨어
        self.global_middlewares.append(self._validate_state_middleware)
        
        # 히스토리 업데이트 미들웨어
        self.global_middlewares.append(self._update_history_middleware)
        
        # 로깅 미들웨어
        self.global_middlewares.append(self._log_state_middleware)
        
        # 성능 모니터링 미들웨어
        self.global_middlewares.append(self._performance_monitoring_middleware)
        
        logger.info("기본 미들웨어 등록 완료")
    
    async def _validate_state_middleware(self, state: Dict[str, Any], node_id: str = None) -> Dict[str, Any]:
        """상태 검증 미들웨어"""
        # 필수 필드 확인
        required_fields = ["query", "task_type", "current_agent"]
        missing_fields = [field for field in required_fields if field not in state]
        
        if missing_fields:
            logger.warning(f"상태에 필요한 필드가 없습니다: {missing_fields}")
            # 빈 필드 초기화
            for field in missing_fields:
                state[field] = ""
        
        # 결과 필드 확인
        if "results" not in state:
            state["results"] = {}
        
        # 히스토리 필드 확인
        if "history" not in state:
            state["history"] = []
        
        return state
    
    async def _update_history_middleware(self, state: Dict[str, Any], node_id: str = None) -> Dict[str, Any]:
        """히스토리 업데이트 미들웨어"""
        # 현재 시간
        current_time = datetime.now().isoformat()
        
        # 히스토리 항목 생성
        history_item = {
            "timestamp": current_time,
            "node": node_id or state.get("current_agent", "unknown"),
            "task_type": state.get("task_type", ""),
            "error": state.get("error_info")
        }
        
        # 히스토리 추가
        if "history" not in state:
            state["history"] = []
        
        state["history"].append(history_item)
        
        return state
    
    async def _log_state_middleware(self, state: Dict[str, Any], node_id: str = None) -> Dict[str, Any]:
        """로깅 미들웨어"""
        # 현재 노드
        current_node = node_id or state.get("current_agent", "unknown")
        
        # 상태 로깅
        logger.info(f"노드 '{current_node}' 상태: task_type='{state.get('task_type', '')}', query='{state.get('query', '')}'")
        
        # 오류 상태 로깅
        if "error_info" in state and state["error_info"]:
            logger.error(f"노드 '{current_node}' 오류: {state['error_info']}")
        
        return state
    
    async def _performance_monitoring_middleware(self, state: Dict[str, Any], node_id: str = None) -> Dict[str, Any]:
        """성능 모니터링 미들웨어"""
        # 현재 시간
        current_time = time.time()
        
        # 노드 시작 시간 설정
        if "node_start_time" not in state:
            state["node_start_time"] = current_time
            return state
        
        # 노드 실행 시간 계산
        node_execution_time = current_time - state["node_start_time"]
        
        # 성능 정보 업데이트
        if "performance" not in state:
            state["performance"] = {}
        
        current_node = node_id or state.get("current_agent", "unknown")
        state["performance"][current_node] = node_execution_time
        
        # 다음 노드를 위한 시작 시간 재설정
        state["node_start_time"] = current_time
        
        return state
    
    def _register_default_event_handlers(self):
        """기본 이벤트 핸들러 등록"""
        # 워크플로우 시작
        async def on_workflow_start(state):
            logger.info(f"워크플로우 시작: {state.get('query', '')}")
        
        # 워크플로우 종료
        async def on_workflow_end(state):
            logger.info(f"워크플로우 종료: {state.get('query', '')}")
        
        # 노드 진입
        async def on_node_entry(state):
            logger.info(f"노드 진입: {state.get('current_node', '')}")
        
        # 노드 종료
        async def on_node_exit(state):
            logger.info(f"노드 종료: {state.get('current_node', '')}")
        
        # 엣지 이동
        async def on_edge_traversal(state):
            edge = state.get("edge", {})
            logger.info(f"엣지 이동: {edge.get('from', '')} -> {edge.get('to', '')}")
        
        # 오류 발생
        async def on_error(state):
            logger.error(f"워크플로우 오류: {state.get('error_info', '')}")
        
        # 이벤트 핸들러 등록
        self.register_event_handler("workflow_start", on_workflow_start)
        self.register_event_handler("workflow_end", on_workflow_end)
        self.register_event_handler("node_entry", on_node_entry)
        self.register_event_handler("node_exit", on_node_exit)
        self.register_event_handler("edge_traversal", on_edge_traversal)
        self.register_event_handler("error", on_error)
        
        logger.info("기본 이벤트 핸들러 등록 완료")
    
    def register_event_handler(self, event_type: str, handler: Callable) -> None:
        """이벤트 핸들러 등록
        
        Args:
            event_type (str): 이벤트 타입
            handler (Callable): 핸들러 함수
        """
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        
        self.event_handlers[event_type].append(handler)
        logger.info(f"이벤트 핸들러 등록: {event_type}")
    
    def unregister_event_handler(self, event_type: str, handler: Callable) -> None:
        """이벤트 핸들러 해제
        
        Args:
            event_type (str): 이벤트 타입
            handler (Callable): 핸들러 함수
        """
        if event_type in self.event_handlers and handler in self.event_handlers[event_type]:
            self.event_handlers[event_type].remove(handler)
            logger.info(f"이벤트 핸들러 해제: {event_type}")
    
    async def _trigger_event(self, event_type: str, state: Dict[str, Any] = None) -> None:
        """이벤트 트리거
        
        Args:
            event_type (str): 이벤트 타입
            state (Dict[str, Any], optional): 상태
        """
        if not state:
            state = {}
        
        if event_type in self.event_handlers:
            for handler in self.event_handlers[event_type]:
                try:
                    await handler(state)
                except Exception as e:
                    logger.error(f"이벤트 핸들러 실행 중 오류: {str(e)}")
    
    async def _create_workflow_graph(self) -> None:
        """워크플로우 그래프 생성"""
        if not self.nodes_config.get("exists", False) or not self.routing_config.get("exists", False):
            logger.error("워크플로우 노드 또는 라우팅 설정 파일이 없습니다.")
            return
        
        # 노드 정보 가져오기
        nodes = self.nodes_config.get("nodes", {})
        
        # 엣지 정보 가져오기
        edges = self.routing_config.get("edges", [])
        
        # 라우팅 규칙 가져오기
        routing_rules = self.routing_config.get("routing_rules", {})
        
        # 진입점 및 종료점 설정
        entry_node = self.workflow_config.get("workflow", {}).get("entry_node", "START")
        end_nodes = self.workflow_config.get("workflow", {}).get("end_nodes", ["END"])
        
        # 핸들러 준비
        handlers = {}
        
        # 각 노드에 대한 핸들러 설정
        for node_id, node_info in nodes.items():
            handler_type = node_info.get("handler_type")
            
            if handler_type == "agent":
                # 에이전트 핸들러
                agent_id = node_info.get("agent_id")
                if agent_id in self.agents:
                    handlers[node_id] = self.agents[agent_id]
                else:
                    logger.warning(f"노드 '{node_id}'의 에이전트 '{agent_id}'가 로드되지 않았습니다.")
            
            elif handler_type == "function":
                # 함수 핸들러
                handler_module = node_info.get("handler_module")
                handler_function = node_info.get("handler_function")
                
                if handler_module and handler_function:
                    try:
                        module = __import__(handler_module, fromlist=[handler_function])
                        handler = getattr(module, handler_function)
                        handlers[node_id] = handler
                    except Exception as e:
                        logger.error(f"노드 '{node_id}'의 핸들러 함수 로드 중 오류: {str(e)}")
            
            elif handler_type == "special":
                # 특수 노드 (START, END, error 등)
                if node_id == "START":
                    handlers[node_id] = self._start_workflow
                elif node_id == "END":
                    handlers[node_id] = self._end_workflow
                elif node_id == "error":
                    handlers[node_id] = self._handle_error
                elif node_id == "success":
                    handlers[node_id] = self._handle_success
                else:
                    handlers[node_id] = self._default_handler
            
            else:
                logger.warning(f"노드 '{node_id}'의 핸들러 타입 '{handler_type}'이 지원되지 않습니다.")
        
        # 워크플로우 그래프 생성
        self.workflow = WorkflowGraph(
            nodes=nodes,
            edges=edges,
            routing_rules=routing_rules,
            handlers=handlers,
            entry_node=entry_node,
            end_nodes=end_nodes
        )
        
        # 이벤트 핸들러 설정
        self.workflow.set_event_handler(self._trigger_event)
        
        # 워크플로우 메트릭 업데이트
        self._workflow_metrics["total_nodes"] = len(nodes)
        self._workflow_metrics["total_edges"] = len(edges)
        
        logger.info(f"워크플로우 그래프 생성 완료: {len(nodes)}개 노드, {len(edges)}개 엣지")
    
    async def _start_workflow(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """워크플로우 시작 핸들러"""
        logger.info(f"워크플로우 시작: {state.get('query', '')}")
        
        # 워크플로우 ID 생성 (없는 경우)
        if "workflow_id" not in state:
            state["workflow_id"] = str(uuid.uuid4())
        
        # 시작 시간 기록
        state["workflow_start_time"] = datetime.now().isoformat()
        
        # 활성 워크플로우 추가
        self._active_workflows.add(state["workflow_id"])
        
        # 워크플로우 메트릭 업데이트
        self._workflow_metrics["total_workflows"] += 1
        self._workflow_metrics["active_workflows"] = len(self._active_workflows)
        
        return state
    
    async def _end_workflow(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """워크플로우 종료 핸들러"""
        logger.info(f"워크플로우 종료: {state.get('query', '')}")
        
        # 종료 시간 기록
        state["workflow_end_time"] = datetime.now().isoformat()
        
        # 워크플로우 ID 확인
        workflow_id = state.get("workflow_id")
        if not workflow_id:
            logger.warning("워크플로우 ID가 없습니다.")
            return state
        
        # 활성 워크플로우에서 제거
        if workflow_id in self._active_workflows:
            self._active_workflows.remove(workflow_id)
        
        # 완료된 워크플로우에 추가
        self._completed_workflows.add(workflow_id)
        
        # 워크플로우 메트릭 업데이트
        self._workflow_metrics["active_workflows"] = len(self._active_workflows)
        self._workflow_metrics["completed_workflows"] = len(self._completed_workflows)
        
        # 평균 완료 시간 계산
        if "workflow_start_time" in state and "workflow_end_time" in state:
            try:
                start_time = datetime.fromisoformat(state["workflow_start_time"])
                end_time = datetime.fromisoformat(state["workflow_end_time"])
                execution_time = (end_time - start_time).total_seconds()
                
                # 평균 완료 시간 업데이트
                current_avg = self._workflow_metrics["avg_completion_time"]
                completed_count = len(self._completed_workflows)
                
                if completed_count > 1:
                    # 기존 평균에 새 값 반영
                    new_avg = ((current_avg * (completed_count - 1)) + execution_time) / completed_count
                else:
                    # 첫 번째 값
                    new_avg = execution_time
                
                self._workflow_metrics["avg_completion_time"] = new_avg
                
            except Exception as e:
                logger.error(f"평균 완료 시간 계산 중 오류: {str(e)}")
        
        return state
    
    async def _handle_error(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """오류 핸들러"""
        error_info = state.get("error_info", "알 수 없는 오류")
        logger.error(f"워크플로우 오류: {error_info}")
        
        # 워크플로우 ID 확인
        workflow_id = state.get("workflow_id")
        if not workflow_id:
            logger.warning("워크플로우 ID가 없습니다.")
            return state
        
        # 활성 워크플로우에서 제거
        if workflow_id in self._active_workflows:
            self._active_workflows.remove(workflow_id)
        
        # 실패한 워크플로우에 추가
        self._failed_workflows.add(workflow_id)
        
        # 워크플로우 메트릭 업데이트
        self._workflow_metrics["active_workflows"] = len(self._active_workflows)
        self._workflow_metrics["failed_workflows"] = len(self._failed_workflows)
        
        # 오류 정보 기록
        self._workflow_metrics["errors"].append({
            "workflow_id": workflow_id,
            "timestamp": datetime.now().isoformat(),
            "error": error_info
        })
        
        # 오류 이벤트 트리거
        await self._trigger_event("error", state)
        
        return state
    
    async def _handle_success(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """성공 핸들러"""
        logger.info(f"워크플로우 성공: {state.get('query', '')}")
        
        # 최종 결과 처리
        results = state.get("results", {})
        
        # 최종 응답 생성
        response = {
            "success": True,
            "query": state.get("query", ""),
            "task_type": state.get("task_type", ""),
            "results": results
        }
        
        # 상태에 응답 저장
        state["final_response"] = response
        
        return state
    
    async def _default_handler(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """기본 핸들러"""
        logger.info(f"기본 핸들러 호출: {state.get('current_node', '알 수 없음')}")
        return state
    
    async def process_query(self, query: str) -> Dict[str, Any]:
        """쿼리 처리
        
        Args:
            query (str): 처리할 쿼리
            
        Returns:
            Dict[str, Any]: 처리 결과
        """
        # 초기화 확인
        if not self._initialized:
            logger.error("워크플로우 매니저가 초기화되지 않았습니다.")
            return {"error": "워크플로우 매니저가 초기화되지 않았습니다."}
        
        # 초기 상태 생성
        state = self.initial_state.copy()
        state["query"] = query
        state["workflow_id"] = str(uuid.uuid4())
        state["timestamp"] = datetime.now().isoformat()
        
        try:
            # 워크플로우 실행
            result = await self.execute_workflow(state)
            return result
            
        except Exception as e:
            logger.error(f"쿼리 처리 중 오류: {str(e)}")
            return {
                "error": f"쿼리 처리 중 오류: {str(e)}",
                "query": query
            }
    
    async def execute_workflow(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """워크플로우 실행
        
        Args:
            state (Dict[str, Any]): 초기 상태
            
        Returns:
            Dict[str, Any]: 최종 상태
        """
        # 초기화 확인
        if not self._initialized:
            logger.error("워크플로우 매니저가 초기화되지 않았습니다.")
            return {"error": "워크플로우 매니저가 초기화되지 않았습니다."}
        
        # 워크플로우 그래프 확인
        if not self.workflow:
            logger.error("워크플로우 그래프가 생성되지 않았습니다.")
            return {"error": "워크플로우 그래프가 생성되지 않았습니다."}
        
        # 워크플로우 ID 확인
        if "workflow_id" not in state:
            state["workflow_id"] = str(uuid.uuid4())
        
        try:
            # 워크플로우 실행
            result = await self.workflow.execute(state)
            
            # 최종 응답 생성
            response = {}
            
            # 오류 확인
            if "error_info" in result and result["error_info"]:
                response["success"] = False
                response["error"] = result["error_info"]
            else:
                response["success"] = True
            
            # 결과 복사
            response["query"] = result.get("query", "")
            response["task_type"] = result.get("task_type", "")
            response["results"] = result.get("results", {})
            
            # 최종 응답이 있는 경우 사용
            if "final_response" in result:
                response = result["final_response"]
            
            return response
            
        except Exception as e:
            logger.error(f"워크플로우 실행 중 오류: {str(e)}")
            return {
                "success": False,
                "error": f"워크플로우 실행 중 오류: {str(e)}",
                "query": state.get("query", "")
            }
    
    def register_node_handler(self, node_id: str, handler: Callable) -> bool:
        """노드 핸들러 등록
        
        Args:
            node_id (str): 노드 ID
            handler (Callable): 핸들러 함수
            
        Returns:
            bool: 등록 성공 여부
        """
        if not self.workflow:
            logger.error("워크플로우 그래프가 생성되지 않았습니다.")
            return False
        
        try:
            self.workflow.handlers[node_id] = handler
            logger.info(f"노드 '{node_id}' 핸들러 등록 성공")
            return True
            
        except Exception as e:
            logger.error(f"노드 핸들러 등록 중 오류: {str(e)}")
            return False

# 싱글톤 인스턴스 반환 함수
def get_workflow_manager(config_dir: str = None) -> WorkflowManager:
    """워크플로우 매니저 인스턴스 반환
    
    Args:
        config_dir (str, optional): 설정 파일 디렉토리
        
    Returns:
        WorkflowManager: 워크플로우 매니저 인스턴스
    """
    global _workflow_manager_instance
    
    if _workflow_manager_instance is None:
        _workflow_manager_instance = WorkflowManager(config_dir)
    
    return _workflow_manager_instance

# 편의 함수
async def create_workflow(config_dir: str = None, message_bus: Optional[MessageBus] = None) -> WorkflowManager:
    """워크플로우 생성 및 초기화
    
    Args:
        config_dir (str, optional): 설정 파일 디렉토리
        message_bus (Optional[MessageBus], optional): 메시지 버스 인스턴스
        
    Returns:
        WorkflowManager: 초기화된 워크플로우 매니저
    """
    manager = get_workflow_manager(config_dir)
    await manager.initialize(message_bus)
    return manager

async def load_workflow_config(config_dir: str) -> bool:
    """워크플로우 설정 로드
    
    Args:
        config_dir (str): 설정 파일 디렉토리
        
    Returns:
        bool: 로드 성공 여부
    """
    manager = get_workflow_manager(config_dir)
    manager.load_configs()
    return True

def register_node_handler(node_id: str, handler: Callable) -> bool:
    """노드 핸들러 등록
    
    Args:
        node_id (str): 노드 ID
        handler (Callable): 핸들러 함수
        
    Returns:
        bool: 등록 성공 여부
    """
    manager = get_workflow_manager()
    return manager.register_node_handler(node_id, handler)

def register_workflow_event_handler(event_type: str, handler: Callable) -> None:
    """워크플로우 이벤트 핸들러 등록
    
    Args:
        event_type (str): 이벤트 타입
        handler (Callable): 핸들러 함수
    """
    manager = get_workflow_manager()
    manager.register_event_handler(event_type, handler)

async def execute_workflow(state: Dict[str, Any]) -> Dict[str, Any]:
    """워크플로우 실행
    
    Args:
        state (Dict[str, Any]): 초기 상태
        
    Returns:
        Dict[str, Any]: 최종 상태
    """
    manager = get_workflow_manager()
    return await manager.execute_workflow(state) 