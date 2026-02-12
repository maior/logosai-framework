"""
작업 분해 협상자

복잡한 작업을 에이전트들이 협상을 통해 분해하고 할당하는 시스템입니다.
에이전트들이 자신의 능력을 고려하여 작업을 나누고 협력 방법을 결정합니다.
"""

import asyncio
import uuid
import time
from typing import Dict, List, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger

from .agent_dialogue_manager import (
    get_dialogue_manager, DialogueType, DialogueTurn,
    DialogueMessage, DialogueSession
)
from .agent_negotiation_protocol import (
    get_negotiation_protocol, NegotiationAction
)
from .agent_self_assessment import CapabilityLevel


class TaskComplexity(Enum):
    """작업 복잡도"""
    SIMPLE = "simple"          # 단일 에이전트로 충분
    MODERATE = "moderate"      # 2-3개 에이전트 협력 필요
    COMPLEX = "complex"        # 여러 에이전트의 긴밀한 협력 필요
    VERY_COMPLEX = "very_complex"  # 대규모 협력 및 조정 필요


class TaskDecompositionStrategy(Enum):
    """작업 분해 전략"""
    FUNCTIONAL = "functional"    # 기능별 분해
    SEQUENTIAL = "sequential"    # 순차적 분해
    PARALLEL = "parallel"        # 병렬 분해
    HIERARCHICAL = "hierarchical"  # 계층적 분해


@dataclass
class SubTask:
    """하위 작업"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    required_capabilities: List[str] = field(default_factory=list)
    assigned_agent: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)  # 다른 SubTask ID들
    estimated_complexity: TaskComplexity = TaskComplexity.SIMPLE
    priority: int = 0  # 높을수록 우선
    status: str = "pending"  # pending, assigned, in_progress, completed, failed
    result: Optional[Any] = None
    

@dataclass
class TaskDecompositionPlan:
    """작업 분해 계획"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    original_task: str = ""
    overall_complexity: TaskComplexity = TaskComplexity.MODERATE
    decomposition_strategy: TaskDecompositionStrategy = TaskDecompositionStrategy.FUNCTIONAL
    subtasks: List[SubTask] = field(default_factory=list)
    agent_assignments: Dict[str, List[str]] = field(default_factory=dict)  # agent_id -> subtask_ids
    execution_order: List[List[str]] = field(default_factory=list)  # 실행 순서 (병렬 가능한 것들은 같은 리스트에)
    estimated_total_time: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    approved_by: Set[str] = field(default_factory=set)
    

class TaskDecompositionNegotiator:
    """작업 분해 협상자"""
    
    def __init__(self):
        self.dialogue_manager = get_dialogue_manager()
        self.negotiation_protocol = get_negotiation_protocol()
        self.active_plans: Dict[str, TaskDecompositionPlan] = {}
        self.completed_plans: List[TaskDecompositionPlan] = []
        
        logger.info("🔨 작업 분해 협상자 초기화 완료")
    
    async def negotiate_task_decomposition(self,
                                         task: str,
                                         available_agents: List[str],
                                         initiator: str = "system",
                                         context: Dict[str, Any] = None) -> TaskDecompositionPlan:
        """
        작업 분해 협상 수행
        
        Args:
            task: 분해할 작업
            available_agents: 참여 가능한 에이전트들
            initiator: 협상 시작자
            context: 추가 컨텍스트
            
        Returns:
            합의된 작업 분해 계획
        """
        logger.info(f"🔨 작업 분해 협상 시작: {task}")
        logger.info(f"   참여 에이전트: {available_agents}")
        
        # 1. 작업 복잡도 평가
        complexity = await self._evaluate_task_complexity(task, context)
        logger.info(f"   복잡도 평가: {complexity.value}")
        
        # 2. 대화 세션 시작
        session_id = await self.dialogue_manager.initiate_dialogue(
            topic=f"작업 분해: {task}",
            participants=available_agents,
            dialogue_type=DialogueType.TASK_PLANNING,
            initiator=initiator,
            context={
                "task": task,
                "complexity": complexity.value,
                **(context or {})
            }
        )
        
        # 3. 초기 계획 생성
        initial_plan = TaskDecompositionPlan(
            original_task=task,
            overall_complexity=complexity,
            decomposition_strategy=self._select_strategy(complexity)
        )
        
        self.active_plans[session_id] = initial_plan
        
        # 4. 브레인스토밍 단계
        await self._brainstorm_subtasks(session_id, task, available_agents)
        
        # 5. 작업 할당 협상
        await self._negotiate_task_assignments(session_id, available_agents)
        
        # 6. 실행 순서 결정
        await self._determine_execution_order(session_id)
        
        # 7. 최종 승인
        approved = await self._get_final_approval(session_id, available_agents)
        
        # 8. 대화 종료
        await self.dialogue_manager.close_dialogue(session_id, "completed")
        
        # 9. 계획 반환
        final_plan = self.active_plans[session_id]
        if approved:
            self.completed_plans.append(final_plan)
            del self.active_plans[session_id]
        
        return final_plan
    
    async def _evaluate_task_complexity(self, task: str, context: Dict[str, Any] = None) -> TaskComplexity:
        """작업 복잡도 평가"""
        # 간단한 휴리스틱 기반 평가 (향후 LLM 기반으로 개선 가능)
        indicators = {
            "simple": ["계산", "검색", "조회", "확인"],
            "moderate": ["분석", "비교", "정리", "요약"],
            "complex": ["설계", "개발", "통합", "최적화"],
            "very_complex": ["전체", "시스템", "아키텍처", "리팩토링"]
        }
        
        task_lower = task.lower()
        
        for complexity, keywords in indicators.items():
            if any(keyword in task_lower for keyword in keywords):
                return TaskComplexity(complexity)
        
        # 기본값
        return TaskComplexity.MODERATE
    
    def _select_strategy(self, complexity: TaskComplexity) -> TaskDecompositionStrategy:
        """복잡도에 따른 분해 전략 선택"""
        strategy_map = {
            TaskComplexity.SIMPLE: TaskDecompositionStrategy.FUNCTIONAL,
            TaskComplexity.MODERATE: TaskDecompositionStrategy.PARALLEL,
            TaskComplexity.COMPLEX: TaskDecompositionStrategy.SEQUENTIAL,
            TaskComplexity.VERY_COMPLEX: TaskDecompositionStrategy.HIERARCHICAL
        }
        return strategy_map.get(complexity, TaskDecompositionStrategy.FUNCTIONAL)
    
    async def _brainstorm_subtasks(self, session_id: str, task: str, agents: List[str]):
        """하위 작업 브레인스토밍"""
        # 시스템이 먼저 제안
        await self.dialogue_manager.add_message(
            session_id,
            DialogueMessage(
                speaker="system",
                turn_type=DialogueTurn.QUESTION,
                content=f"'{task}' 작업을 어떻게 나누면 좋을까요? 각자 할 수 있는 부분을 제안해주세요.",
                metadata={"phase": "brainstorming"}
            )
        )
        
        # 각 에이전트가 제안할 시간 제공
        await asyncio.sleep(2)  # 실제로는 에이전트 응답을 기다림
        
        # 제안된 내용을 수집하여 하위 작업으로 변환
        messages = self.dialogue_manager.get_session_messages(session_id)
        
        plan = self.active_plans[session_id]
        
        # 예시 하위 작업들 (실제로는 에이전트 제안에서 추출)
        if "계산" in task:
            plan.subtasks.extend([
                SubTask(
                    description="수식 파싱 및 검증",
                    required_capabilities=["mathematical_computation", "parsing"],
                    estimated_complexity=TaskComplexity.SIMPLE,
                    priority=1
                ),
                SubTask(
                    description="계산 수행",
                    required_capabilities=["mathematical_computation"],
                    estimated_complexity=TaskComplexity.SIMPLE,
                    priority=2,
                    dependencies=[]  # 첫 번째 작업에 의존
                )
            ])
        elif "분석" in task:
            plan.subtasks.extend([
                SubTask(
                    description="데이터 수집",
                    required_capabilities=["data_collection", "web_search"],
                    estimated_complexity=TaskComplexity.MODERATE,
                    priority=1
                ),
                SubTask(
                    description="데이터 분석",
                    required_capabilities=["data_analysis", "statistics"],
                    estimated_complexity=TaskComplexity.MODERATE,
                    priority=2
                ),
                SubTask(
                    description="결과 시각화",
                    required_capabilities=["visualization", "reporting"],
                    estimated_complexity=TaskComplexity.SIMPLE,
                    priority=3
                )
            ])
    
    async def _negotiate_task_assignments(self, session_id: str, agents: List[str]):
        """작업 할당 협상"""
        plan = self.active_plans[session_id]
        
        # 각 하위 작업에 대해 자원하는 에이전트 모집
        for subtask in plan.subtasks:
            await self.dialogue_manager.add_message(
                session_id,
                DialogueMessage(
                    speaker="system",
                    turn_type=DialogueTurn.QUESTION,
                    content=f"누가 '{subtask.description}' 작업을 담당하시겠습니까? 필요 능력: {', '.join(subtask.required_capabilities)}",
                    metadata={"subtask_id": subtask.id, "phase": "assignment"}
                )
            )
            
            # 실제로는 에이전트들의 자원 응답을 기다리고 평가
            # 여기서는 간단히 첫 번째 에이전트에 할당
            if agents:
                subtask.assigned_agent = agents[0]
                plan.agent_assignments.setdefault(agents[0], []).append(subtask.id)
                
                # 할당 확인 메시지
                await self.dialogue_manager.add_message(
                    session_id,
                    DialogueMessage(
                        speaker=agents[0],
                        turn_type=DialogueTurn.AGREEMENT,
                        content=f"제가 '{subtask.description}' 작업을 담당하겠습니다.",
                        metadata={"subtask_id": subtask.id}
                    )
                )
                
                # 다음 작업은 다른 에이전트에게 (라운드 로빈)
                agents = agents[1:] + agents[:1]
    
    async def _determine_execution_order(self, session_id: str):
        """실행 순서 결정"""
        plan = self.active_plans[session_id]
        
        # 의존성을 고려한 실행 순서 결정
        # 간단한 구현: 우선순위와 의존성 기반
        
        # 의존성이 없는 작업들을 먼저 찾기
        independent_tasks = [
            subtask for subtask in plan.subtasks
            if not subtask.dependencies
        ]
        
        # 우선순위별로 정렬
        independent_tasks.sort(key=lambda x: x.priority)
        
        # 병렬 실행 가능한 그룹으로 묶기
        execution_groups = []
        current_priority = None
        current_group = []
        
        for task in independent_tasks:
            if current_priority != task.priority:
                if current_group:
                    execution_groups.append(current_group)
                current_group = [task.id]
                current_priority = task.priority
            else:
                current_group.append(task.id)
        
        if current_group:
            execution_groups.append(current_group)
        
        plan.execution_order = execution_groups
        
        # 실행 순서 발표
        await self.dialogue_manager.add_message(
            session_id,
            DialogueMessage(
                speaker="system",
                turn_type=DialogueTurn.SUMMARY,
                content=f"실행 순서가 결정되었습니다. 총 {len(execution_groups)}개 단계로 진행됩니다.",
                metadata={"execution_order": execution_groups}
            )
        )
    
    async def _get_final_approval(self, session_id: str, agents: List[str]) -> bool:
        """최종 승인 요청"""
        plan = self.active_plans[session_id]
        
        # 계획 요약
        summary = self._generate_plan_summary(plan)
        
        await self.dialogue_manager.add_message(
            session_id,
            DialogueMessage(
                speaker="system",
                turn_type=DialogueTurn.PROPOSAL,
                content=f"최종 작업 분해 계획입니다:\n{summary}\n\n모두 동의하시면 실행하겠습니다.",
                metadata={"phase": "approval", "plan_id": plan.id}
            )
        )
        
        # 실제로는 모든 에이전트의 동의를 기다림
        # 여기서는 자동 승인
        for agent in agents:
            plan.approved_by.add(agent)
        
        return len(plan.approved_by) >= len(agents) * 0.5  # 50% 이상 동의
    
    def _generate_plan_summary(self, plan: TaskDecompositionPlan) -> str:
        """계획 요약 생성"""
        lines = [
            f"원본 작업: {plan.original_task}",
            f"복잡도: {plan.overall_complexity.value}",
            f"전략: {plan.decomposition_strategy.value}",
            f"하위 작업 수: {len(plan.subtasks)}",
            ""
        ]
        
        for i, subtask in enumerate(plan.subtasks, 1):
            lines.append(f"{i}. {subtask.description}")
            lines.append(f"   담당: {subtask.assigned_agent or '미할당'}")
            lines.append(f"   복잡도: {subtask.estimated_complexity.value}")
            lines.append("")
        
        return "\n".join(lines)
    
    def get_plan_by_id(self, plan_id: str) -> Optional[TaskDecompositionPlan]:
        """ID로 계획 조회"""
        # 활성 계획에서 찾기
        for plan in self.active_plans.values():
            if plan.id == plan_id:
                return plan
        
        # 완료된 계획에서 찾기
        for plan in self.completed_plans:
            if plan.id == plan_id:
                return plan
        
        return None
    
    async def execute_plan(self, plan_id: str) -> Dict[str, Any]:
        """계획 실행 (실제 작업 수행)"""
        plan = self.get_plan_by_id(plan_id)
        if not plan:
            return {"error": "계획을 찾을 수 없습니다."}
        
        results = {}
        
        # 실행 순서에 따라 작업 수행
        for group in plan.execution_order:
            # 병렬 실행 가능한 작업들
            tasks = []
            for subtask_id in group:
                subtask = next((st for st in plan.subtasks if st.id == subtask_id), None)
                if subtask and subtask.assigned_agent:
                    # 실제로는 에이전트에게 작업 요청
                    # 여기서는 시뮬레이션
                    tasks.append(self._execute_subtask(subtask))
            
            # 병렬 실행
            if tasks:
                group_results = await asyncio.gather(*tasks)
                for subtask_id, result in zip(group, group_results):
                    results[subtask_id] = result
        
        return {
            "plan_id": plan_id,
            "status": "completed",
            "results": results,
            "execution_time": time.time() - plan.created_at
        }
    
    async def _execute_subtask(self, subtask: SubTask) -> Dict[str, Any]:
        """하위 작업 실행 (시뮬레이션)"""
        # 실제로는 할당된 에이전트의 process 메서드 호출
        await asyncio.sleep(1)  # 작업 시뮬레이션
        
        subtask.status = "completed"
        subtask.result = f"{subtask.description} 완료"
        
        return {
            "subtask_id": subtask.id,
            "status": "completed",
            "result": subtask.result
        }


# 전역 인스턴스
_task_decomposition_negotiator = None


def get_task_decomposition_negotiator() -> TaskDecompositionNegotiator:
    """전역 작업 분해 협상자 인스턴스 반환"""
    global _task_decomposition_negotiator
    if _task_decomposition_negotiator is None:
        _task_decomposition_negotiator = TaskDecompositionNegotiator()
    return _task_decomposition_negotiator