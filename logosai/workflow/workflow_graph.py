"""
LogosAI 워크플로우 그래프 모듈

이 모듈은 LogosAI 에이전트들 간의 워크플로우 그래프를 관리하기 위한 기능을 제공합니다.
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Any, Callable, Optional, Set, Union, TypeVar
import logging

# 로거 설정
logger = logging.getLogger(__name__)

# 싱글톤 인스턴스
_default_workflow_graph = None

State = TypeVar('State', bound=Dict[str, Any])

class WorkflowGraph:
    """워크플로우 그래프 클래스"""
    
    def __init__(self, nodes, edges, routing_rules, handlers, entry_node, end_nodes, max_visits=3):
        """
        워크플로우 그래프 초기화
        
        Args:
            nodes: 노드 정보 (리스트 또는 딕셔너리)
            edges: 엣지 정보 리스트
            routing_rules: 라우팅 규칙 딕셔너리
            handlers: 노드 핸들러 함수 딕셔너리
            entry_node: 시작 노드 ID
            end_nodes: 종료 노드 ID 리스트
            max_visits: 각 노드의 최대 방문 횟수 (기본값: 3)
        """
        # 노드 리스트가 전달된 경우 딕셔너리로 변환
        if isinstance(nodes, list):
            self.nodes = {node_id: {} for node_id in nodes}
        else:
            self.nodes = nodes
            
        self.edges = edges
        self.routing_rules = routing_rules
        self.handlers = handlers
        self.entry_node = entry_node
        self.end_nodes = end_nodes if isinstance(end_nodes, list) else [end_nodes]
        self.event_handler = None
        self.max_visits_per_node = max_visits
        
    def set_event_handler(self, event_handler: Callable):
        """
        이벤트 핸들러 설정
        
        Args:
            event_handler: 이벤트 핸들러 함수
        """
        self.event_handler = event_handler
    
    async def _execute_node_handler(self, node_id: str, handler: Any, state: Dict[str, Any]) -> Dict[str, Any]:
        """노드 핸들러 실행 (중복 코드 제거용 헬퍼 메서드)"""
        if handler is None:
            # 핸들러가 None인 경우(특수 노드) 상태를 그대로 전달
            logger.info(f"노드 {node_id}는 특수 노드로 핸들러 없이 통과합니다.")
            return state
            
        # 핸들러가 있는 경우 실행
        try:
            # 함수인 경우 직접 호출
            if callable(handler):
                return await handler(state)
            # 에이전트 객체인 경우 process 메서드 호출
            elif hasattr(handler, 'process') and callable(handler.process):
                # 상태 전체를 전달
                result = await handler.process(state)
                
                # 결과 저장
                if "results" not in state:
                    state["results"] = {}
                    
                # AgentResponse 객체 또는 다른 결과 형식 처리
                if hasattr(result, 'content'):
                    state["results"][node_id] = result.content
                    # task_type이 결과에 포함되어 있으면 상태 업데이트
                    if hasattr(result, 'task_type'):
                        state["task_type"] = result.task_type
                else:
                    state["results"][node_id] = result
                    
                return state
            else:
                # 호출 불가능한 핸들러
                error_msg = f"노드 {node_id}의 핸들러는 호출할 수 없습니다: {type(handler)}"
                logger.error(error_msg)
                state["error_info"] = error_msg
                state["last_error_node"] = node_id
                return state
        except Exception as e:
            # 핸들러 실행 중 오류 발생
            error_msg = f"노드 {node_id} 핸들러 실행 중 오류: {str(e)}"
            logger.error(error_msg)
            state["error_info"] = error_msg
            state["last_error_node"] = node_id
            return state
    
    async def _determine_next_node(self, current_node: str, state: Dict[str, Any]) -> Optional[str]:
        """다음 노드 결정 (라우팅 로직)"""
        # 오류 상태 확인
        has_error = "error_info" in state and state["error_info"] is not None
        if has_error and current_node != "error":
            logger.warning(f"노드 {current_node} 처리 중 오류 발생: {state['error_info']}")
            return "error"
            
        # 라우팅 규칙이 있는지 확인
        if current_node in self.routing_rules:
            rules = self.routing_rules[current_node]
            
            # 라우팅 규칙이 딕셔너리인 경우
            if isinstance(rules, dict):
                # conditions와 default가 있는 구조
                if "conditions" in rules and "default" in rules:
                    # task_type에 따른 라우팅 처리
                    task_type = state.get("task_type", "")
                    conditions = rules.get("conditions", {})
                    
                    # task_type이 있고 해당 조건이 있는 경우
                    if task_type and task_type in conditions:
                        next_node = conditions[task_type]
                        if next_node is not None:
                            logger.info(f"라우팅 규칙 적용 (task_type={task_type}): {current_node} -> {next_node}")
                            return next_node
                    
                    # 기본 라우팅 사용
                    next_node = rules.get("default")
                    if next_node is not None:
                        logger.info(f"기본 라우팅 적용: {current_node} -> {next_node}")
                        return next_node
                
                # target이 직접 있는 경우
                elif "target" in rules:
                    next_node = rules["target"]
                    logger.info(f"다이렉트 라우팅: {current_node} -> {next_node}")
                    return next_node
            
            # 라우팅 규칙이 문자열인 경우
            elif isinstance(rules, str):
                next_node = rules
                logger.info(f"문자열 라우팅: {current_node} -> {next_node}")
                return next_node
            
            # 라우팅 규칙이 리스트인 경우
            elif isinstance(rules, list):
                for rule in rules:
                    if isinstance(rule, str):
                        # 문자열 형태의 규칙이 있는 경우 무시
                        logger.warning(f"문자열 형태의 라우팅 규칙을 건너뜁니다: {rule}")
                        continue
                        
                    target = rule.get("target")
                    condition = rule.get("condition")
                    
                    # 오류가 있으면 error 노드로 라우팅
                    if has_error and target == "error":
                        logger.warning(f"오류가 발견되어 error 노드로 라우팅합니다: {state.get('error_info')}")
                        return target
                        
                    # 조건 검사
                    if self._evaluate_condition(condition, state):
                        logger.info(f"조건 통과, 라우팅: {current_node} -> {target}")
                        return target
        
        # 다음 노드가 결정되지 않았으면 기본 라우팅 시도 (task_type 기반)
        task_type = state.get("task_type", "")
        if task_type:
            # task_type이 있으면 그에 맞는 노드로 이동
            if task_type in self.nodes:
                next_node = task_type
                logger.info(f"task_type에 따른 기본 라우팅: {current_node} -> {next_node}")
                return next_node
            else:
                # 해당 task_type의 노드가 없으면 오류
                error_msg = f"노드 {current_node}에서 task_type {task_type}에 맞는 노드를 찾을 수 없습니다."
                logger.error(error_msg)
                state["error_info"] = error_msg
                state["last_error_node"] = current_node
                return "error"
        else:
            # task_type이 없으면 오류
            error_msg = f"노드 {current_node}에서 다음 노드를 결정할 수 없습니다. task_type이 없습니다."
            logger.error(error_msg)
            state["error_info"] = error_msg
            state["last_error_node"] = current_node
            return "error"
            
    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        워크플로우 실행
        
        Args:
            state: 초기 상태
            
        Returns:
            Dict[str, Any]: 최종 상태
        """
        current_node = self.entry_node
        logger.debug(f"워크플로우 시작: 초기 노드 = {self.entry_node}")
        
        # 현재 노드 추적
        state["current_node"] = current_node
        
        # 무한 루프 방지를 위한 방문 노드 추적
        visit_counts = {}
        
        # 시작 시간 기록
        state["workflow_start_time"] = datetime.now().isoformat()
        
        # 워크플로우 시작 이벤트 트리거
        await self.trigger_event("workflow_start", state)
        
        # 상태 초기화
        if "history" not in state:
            state["history"] = []
        
        # 워크플로우 실행
        while current_node not in self.end_nodes:
            # 방문 횟수 증가
            visit_counts[current_node] = visit_counts.get(current_node, 0) + 1
            
            # 노드 방문 제한 초과 확인
            if visit_counts.get(current_node, 0) > self.max_visits_per_node:
                error_msg = f"노드 {current_node}의 최대 방문 횟수({self.max_visits_per_node})를 초과했습니다."
                logger.error(error_msg)
                state["error_info"] = error_msg
                state["last_error_node"] = current_node
                current_node = "error"
                
            # 현재 노드 상태 업데이트
            state["current_node"] = current_node
            
            # 노드 진입 이벤트 트리거
            await self.trigger_event("node_entry", state)
            
            # 핸들러 가져오기
            handler = self.handlers.get(current_node)
            
            # 핸들러 실행
            state = await self._execute_node_handler(current_node, handler, state)
            
            # 노드 종료 이벤트 트리거
            await self.trigger_event("node_exit", state)
            
            # 실행 이력 기록
            state["history"].append({
                "node": current_node,
                "timestamp": datetime.now().isoformat(),
                "task_type": state.get("task_type", ""),
                "error": state.get("error_info")
            })
            
            # 다음 노드 결정
            next_node = await self._determine_next_node(current_node, state)
            
            # 다음 노드가 null이면 워크플로우 종료
            if next_node is None:
                logger.warning(f"노드 {current_node}에서 다음 노드가 결정되지 않았습니다. 워크플로우 종료.")
                next_node = "END"
                
            # 엣지 이벤트 트리거
            state["edge"] = {"from": current_node, "to": next_node}
            await self.trigger_edge_event(state)
            
            # 현재 노드 업데이트
            current_node = next_node
            state["current_node"] = current_node
            
        # 종료 노드에 도달
        # 종료 노드 핸들러 있으면 실행
        if current_node in self.handlers:
            handler = self.handlers.get(current_node)
            state = await self._execute_node_handler(current_node, handler, state)
            
        # 종료 시간 기록
        state["workflow_end_time"] = datetime.now().isoformat()
        
        # 워크플로우 종료 이벤트 트리거
        await self.trigger_event("workflow_end", state)
        
        return state
        
    async def trigger_event(self, event_type: str, state: Dict[str, Any]) -> None:
        """이벤트 트리거"""
        if self.event_handler:
            try:
                await self.event_handler(event_type, state)
            except Exception as e:
                logger.error(f"이벤트 핸들러 실행 중 오류: {str(e)}")
                
    async def trigger_edge_event(self, state: Dict[str, Any]) -> None:
        """엣지 이벤트 트리거"""
        if self.event_handler:
            try:
                await self.event_handler("edge_traversal", state)
            except Exception as e:
                logger.error(f"엣지 이벤트 핸들러 실행 중 오류: {str(e)}")
                
    def _evaluate_condition(self, condition, state):
        """조건 평가"""
        if not condition:
            return True
            
        if isinstance(condition, str):
            # 조건이 문자열인 경우
            return condition == state.get("task_type", "")
            
        if isinstance(condition, dict):
            # 조건이 딕셔너리인 경우
            field = condition.get("field", "task_type")
            value = condition.get("value")
            operator = condition.get("operator", "eq")
            
            # 필드 값 추출
            field_value = state.get(field)
            
            # 연산자에 따른 비교
            if operator == "eq":
                return field_value == value
            elif operator == "ne":
                return field_value != value
            elif operator == "in":
                return field_value in value
            elif operator == "not_in":
                return field_value not in value
            elif operator == "exists":
                return field in state
            elif operator == "not_exists":
                return field not in state
                
        return False


def create_workflow_graph(
    nodes: Dict[str, Any],
    edges: List[Dict[str, Any]],
    routing_rules: Dict[str, Any],
    handlers: Dict[str, Callable],
    entry_node: str = "START",
    end_nodes: Union[str, List[str]] = "END",
    max_visits: int = 3
) -> WorkflowGraph:
    """
    워크플로우 그래프 생성
    
    Args:
        nodes: 노드 정보 딕셔너리
        edges: 엣지 정보 리스트
        routing_rules: 라우팅 규칙
        handlers: 노드 핸들러 함수 딕셔너리
        entry_node: 시작 노드 ID (기본값: "START")
        end_nodes: 종료 노드 ID 또는 리스트 (기본값: "END")
        max_visits: 각 노드의 최대 방문 횟수 (기본값: 3)
        
    Returns:
        WorkflowGraph: 생성된 워크플로우 그래프
    """
    return WorkflowGraph(
        nodes=nodes,
        edges=edges,
        routing_rules=routing_rules,
        handlers=handlers,
        entry_node=entry_node,
        end_nodes=end_nodes,
        max_visits=max_visits
    )

def get_default_workflow_graph() -> Optional[WorkflowGraph]:
    """
    기본 워크플로우 그래프 반환
    
    Returns:
        Optional[WorkflowGraph]: 기본 워크플로우 그래프 또는 None
    """
    global _default_workflow_graph
    return _default_workflow_graph 