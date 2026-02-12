"""
LogosAI Advanced Multi-Agent Manager

지능형 에이전트 협상 시스템을 통한 혁신적인 다중 에이전트 관리자입니다.
사용자 쿼리를 분석하고, 에이전트들과 실시간 협상을 통해 최적의 처리 방법을 결정합니다.

LogosAI Framework의 핵심 특장점:
- 에이전트 자기평가 기반 투명한 의사결정
- 실시간 에이전트-매니저 협상
- 동적 작업 할당 및 핸드오프
- 다중 에이전트 협력 워크플로우
"""

import asyncio
import time
from typing import Dict, Any, List, Optional, Union, Tuple
from dataclasses import dataclass
from enum import Enum
from loguru import logger
import json

from .agent_self_assessment import (
    AgentSelfAssessment, SelfAssessmentResult, CapabilityLevel,
    create_agent_self_assessment
)
from .agent_negotiation_protocol import (
    AgentNegotiationProtocol, NegotiationStatus,
    get_negotiation_protocol
)
from .agent_selector import AgentSelector
from .task_decomposition_negotiator import (
    TaskDecompositionNegotiator, TaskComplexity,
    get_task_decomposition_negotiator
)
from .agent_dialogue_manager import get_dialogue_manager

class ProcessingMode(Enum):
    """처리 모드"""
    SINGLE_AGENT = "single_agent"           # 단일 에이전트
    HANDOFF = "handoff"                     # 에이전트 핸드오프
    COLLABORATIVE = "collaborative"         # 협력 모드
    PIPELINE = "pipeline"                   # 파이프라인 처리
    FALLBACK = "fallback"                   # 폴백 처리
    DECOMPOSED = "decomposed"               # 작업 분해 처리

@dataclass
class ProcessingResult:
    """처리 결과"""
    success: bool
    result: Any
    mode: ProcessingMode
    primary_agent: str
    participating_agents: List[str]
    processing_time: float
    negotiation_summary: Dict[str, Any]
    error_message: Optional[str] = None

class AdvancedMultiAgentManager:
    """지능형 다중 에이전트 매니저"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """
        매니저 초기화
        
        Args:
            config: 매니저 설정
        """
        self.config = config or {}
        self.manager_id = "advanced_multi_agent_manager"
        
        # 코어 시스템 초기화
        self.agent_selector = AgentSelector(config.get("agent_selector", {}))
        self.negotiation_protocol = get_negotiation_protocol()
        self.task_decomposition_negotiator = get_task_decomposition_negotiator()
        self.dialogue_manager = get_dialogue_manager()
        
        # 에이전트 레지스트리
        self.registered_agents: Dict[str, Any] = {}
        self.agent_assessments: Dict[str, AgentSelfAssessment] = {}
        self.agent_instances: Dict[str, Any] = {}
        
        # 성능 추적
        self.processing_history: List[Dict[str, Any]] = []
        self.agent_performance: Dict[str, Dict[str, float]] = {}
        
        logger.info(f"🤖 {self.manager_id} 초기화 완료")
    
    def register_agent(self, agent_id: str, agent_instance: Any, 
                      agent_config: Dict[str, Any] = None):
        """
        에이전트 등록
        
        Args:
            agent_id: 에이전트 ID
            agent_instance: 에이전트 인스턴스
            agent_config: 에이전트 설정
        """
        self.registered_agents[agent_id] = agent_config or {}
        self.agent_instances[agent_id] = agent_instance
        
        # 자기평가 시스템 생성 및 등록
        assessment = create_agent_self_assessment(
            agent_id=agent_id,
            agent_name=agent_config.get("name", agent_id) if agent_config else agent_id,
            agent_config=agent_config,
            llm_client=getattr(agent_instance, 'llm_client', None)
        )
        
        self.agent_assessments[agent_id] = assessment
        self.negotiation_protocol.register_agent_assessment(agent_id, assessment)
        
        logger.info(f"✅ 에이전트 등록 완료: {agent_id}")
        
        # 에이전트별 도메인 키워드 설정 (예시)
        if agent_id == "rag_agent":
            assessment.set_domain_keywords({
                "document": ["pdf", "문서", "논문", "보고서", "파일", "document", "paper", "report"],
                "search": ["검색", "찾", "search", "find", "lookup", "retrieve"],
                "research": ["연구", "박사", "학술", "research", "academic", "study"],
                "analysis": ["분석", "해석", "analysis", "interpret", "examine"]
            })
            assessment.set_capabilities([
                "PDF 문서 검색 및 정보 추출",
                "학술 논문 및 연구 자료 분석", 
                "다중 문서 검색 및 비교",
                "RAG 기반 질의응답",
                "문서 내 특정 정보 검색"
            ])
            
        elif agent_id == "math_agent":
            assessment.set_domain_keywords({
                "math": ["수학", "계산", "방정식", "math", "calculate", "equation", "formula"],
                "computation": ["연산", "계산", "compute", "calculation", "arithmetic"],
                "statistics": ["통계", "확률", "statistics", "probability", "data"]
            })
            assessment.set_capabilities([
                "수학 문제 해결",
                "방정식 및 수식 계산",
                "통계 분석 및 데이터 처리",
                "수치 해석 및 모델링"
            ])
            
        elif agent_id == "web_search_agent":
            assessment.set_domain_keywords({
                "web": ["웹", "인터넷", "온라인", "web", "internet", "online"],
                "search": ["검색", "찾", "search", "find", "lookup"],
                "current": ["최신", "실시간", "current", "latest", "real-time"]
            })
            assessment.set_capabilities([
                "웹 검색 및 정보 수집",
                "실시간 정보 조회",
                "온라인 리소스 검색",
                "최신 뉴스 및 동향 파악"
            ])
    
    async def _evaluate_request_complexity(self, user_request: str, context: Dict[str, Any] = None) -> TaskComplexity:
        """요청의 복잡도 평가"""
        # 간단한 휴리스틱 기반 평가
        request_lower = user_request.lower()
        
        # 복잡도 지표
        complexity_score = 0
        
        # 작업 수 지표
        task_indicators = ["그리고", "또한", "동시에", "함께", "and", "also", "additionally"]
        task_count = sum(1 for indicator in task_indicators if indicator in request_lower)
        complexity_score += task_count * 0.3
        
        # 분석/통합 지표
        complex_verbs = ["분석", "통합", "설계", "최적화", "구현", "개발", "analyze", "integrate", "design", "optimize"]
        if any(verb in request_lower for verb in complex_verbs):
            complexity_score += 0.5
        
        # 데이터 규모 지표
        scale_indicators = ["전체", "모든", "대규모", "전사", "all", "entire", "large-scale", "comprehensive"]
        if any(indicator in request_lower for indicator in scale_indicators):
            complexity_score += 0.4
        
        # 조건/요구사항 지표
        condition_count = request_lower.count("조건") + request_lower.count("요구사항") + request_lower.count("if") + request_lower.count("requirement")
        complexity_score += condition_count * 0.2
        
        # 복잡도 결정
        if complexity_score >= 1.5:
            return TaskComplexity.VERY_COMPLEX
        elif complexity_score >= 1.0:
            return TaskComplexity.COMPLEX
        elif complexity_score >= 0.5:
            return TaskComplexity.MODERATE
        else:
            return TaskComplexity.SIMPLE
    
    async def process_user_request(self, user_request: str, 
                                 context: Dict[str, Any] = None) -> ProcessingResult:
        """
        사용자 요청 처리 (메인 엔트리 포인트)
        
        Args:
            user_request: 사용자 요청
            context: 추가 컨텍스트
            
        Returns:
            ProcessingResult: 처리 결과
        """
        start_time = time.time()
        context = context or {}
        
        logger.info(f"🚀 사용자 요청 처리 시작: '{user_request[:100]}...'")
        
        try:
            # 1단계: 작업 복잡도 평가
            complexity = await self._evaluate_request_complexity(user_request, context)
            logger.info(f"📊 작업 복잡도: {complexity.value}")
            
            # 2단계: 복잡한 작업인 경우 작업 분해 협상
            if complexity in [TaskComplexity.COMPLEX, TaskComplexity.VERY_COMPLEX]:
                logger.info(f"🔨 복잡한 작업으로 판단, 작업 분해 협상 시작")
                
                # 사용 가능한 에이전트 목록
                available_agents = list(self.agent_instances.keys())
                
                # 작업 분해 협상
                decomposition_plan = await self.task_decomposition_negotiator.negotiate_task_decomposition(
                    task=user_request,
                    available_agents=available_agents,
                    initiator=self.manager_id,
                    context=context
                )
                
                # 분해된 작업 실행
                return await self._execute_decomposed_plan(decomposition_plan, context, start_time)
            
            # 3단계: 단순/중간 복잡도는 기존 방식으로 처리
            # 1차 에이전트 선택
            primary_agent_id = await self._select_primary_agent(user_request, context)
            
            if not primary_agent_id:
                return ProcessingResult(
                    success=False,
                    result=None,
                    mode=ProcessingMode.FALLBACK,
                    primary_agent="none",
                    participating_agents=[],
                    processing_time=time.time() - start_time,
                    negotiation_summary={"error": "적합한 에이전트를 찾을 수 없음"},
                    error_message="적합한 에이전트를 찾을 수 없습니다."
                )
            
            # 2단계: 에이전트와 협상 진행
            logger.info(f"🤝 {primary_agent_id}와 협상 시작")
            
            session_id = await self.negotiation_protocol.initiate_negotiation(
                user_request=user_request,
                primary_agent_id=primary_agent_id,
                context=context
            )
            
            # 3단계: 협상 결과에 따른 처리
            negotiation_result = await self.negotiation_protocol.conduct_negotiation(session_id)
            
            # 4단계: 실제 작업 실행
            processing_result = await self._execute_processing(
                user_request, negotiation_result, context, session_id
            )
            
            # 5단계: 성능 추적 업데이트
            await self._update_performance_tracking(
                processing_result, negotiation_result, time.time() - start_time
            )
            
            return processing_result
            
        except Exception as e:
            logger.error(f"❌ 사용자 요청 처리 실패: {str(e)}")
            return ProcessingResult(
                success=False,
                result=None,
                mode=ProcessingMode.FALLBACK,
                primary_agent="error",
                participating_agents=[],
                processing_time=time.time() - start_time,
                negotiation_summary={"error": str(e)},
                error_message=f"처리 중 오류 발생: {str(e)}"
            )
    
    async def _select_primary_agent(self, user_request: str, 
                                  context: Dict[str, Any]) -> Optional[str]:
        """1차 에이전트 선택"""
        
        # 기존 AgentSelector를 사용하여 후보 에이전트들 선택
        agent_configs = [
            {"agent_id": agent_id, **config}
            for agent_id, config in self.registered_agents.items()
        ]
        
        if not agent_configs:
            logger.warning("등록된 에이전트가 없습니다.")
            return None
        
        # 상위 후보들 선택
        top_agents = await self.agent_selector.select_best_agents(
            request=user_request,
            agent_configs=agent_configs,
            max_results=3
        )
        
        if not top_agents:
            logger.warning("적합한 에이전트를 찾을 수 없습니다.")
            return None
        
        # 가장 점수가 높은 에이전트를 1차 선택
        primary_agent = top_agents[0]
        logger.info(f"🎯 1차 에이전트 선택: {primary_agent.agent_id} (점수: {primary_agent.overall_score:.3f})")
        
        return primary_agent.agent_id
    
    async def _execute_processing(self, user_request: str, 
                                negotiation_result: Dict[str, Any],
                                context: Dict[str, Any],
                                session_id: str) -> ProcessingResult:
        """협상 결과에 따른 실제 처리 실행"""
        
        mode = negotiation_result.get("mode", "failed")
        selected_agent = negotiation_result.get("selected_agent")
        
        logger.info(f"🔄 처리 모드: {mode}, 선택된 에이전트: {selected_agent}")
        
        processing_start = time.time()
        
        try:
            if mode == "single_agent" and selected_agent in self.agent_instances:
                # 단일 에이전트 처리
                result = await self._execute_single_agent(
                    selected_agent, user_request, context
                )
                
                return ProcessingResult(
                    success=True,
                    result=result,
                    mode=ProcessingMode.SINGLE_AGENT,
                    primary_agent=selected_agent,
                    participating_agents=[selected_agent],
                    processing_time=time.time() - processing_start,
                    negotiation_summary=self.negotiation_protocol.get_session_summary(session_id)
                )
                
            elif mode == "handoff":
                # 에이전트 핸드오프 처리
                result = await self._execute_handoff(
                    negotiation_result, user_request, context
                )
                
                return ProcessingResult(
                    success=True,
                    result=result,
                    mode=ProcessingMode.HANDOFF,
                    primary_agent=selected_agent,
                    participating_agents=[selected_agent],
                    processing_time=time.time() - processing_start,
                    negotiation_summary=self.negotiation_protocol.get_session_summary(session_id)
                )
                
            elif mode == "collaborative":
                # 협력 모드 처리
                result = await self._execute_collaborative(
                    negotiation_result, user_request, context
                )
                
                participating_agents = [
                    agent["agent_id"] 
                    for agent in negotiation_result.get("participating_agents", [])
                ]
                
                return ProcessingResult(
                    success=True,
                    result=result,
                    mode=ProcessingMode.COLLABORATIVE,
                    primary_agent=negotiation_result.get("coordinator", "collaborative"),
                    participating_agents=participating_agents,
                    processing_time=time.time() - processing_start,
                    negotiation_summary=self.negotiation_protocol.get_session_summary(session_id)
                )
                
            else:
                # 처리 실패
                error_msg = negotiation_result.get("reason", "알 수 없는 오류")
                
                return ProcessingResult(
                    success=False,
                    result=None,
                    mode=ProcessingMode.FALLBACK,
                    primary_agent="none",
                    participating_agents=[],
                    processing_time=time.time() - processing_start,
                    negotiation_summary=self.negotiation_protocol.get_session_summary(session_id),
                    error_message=error_msg
                )
                
        except Exception as e:
            logger.error(f"❌ 처리 실행 중 오류: {str(e)}")
            
            return ProcessingResult(
                success=False,
                result=None,
                mode=ProcessingMode.FALLBACK,
                primary_agent="error",
                participating_agents=[],
                processing_time=time.time() - processing_start,
                negotiation_summary=self.negotiation_protocol.get_session_summary(session_id),
                error_message=f"실행 오류: {str(e)}"
            )
    
    async def _execute_single_agent(self, agent_id: str, user_request: str,
                                  context: Dict[str, Any]) -> Any:
        """단일 에이전트 실행"""
        logger.info(f"🤖 단일 에이전트 실행: {agent_id}")
        
        agent = self.agent_instances[agent_id]
        
        # 에이전트 인터페이스에 따라 적절한 메서드 호출
        if hasattr(agent, 'process'):
            # 표준 process 메서드
            return await agent.process(user_request)
        elif hasattr(agent, 'run'):
            # run 메서드
            return await agent.run(user_request)
        elif hasattr(agent, 'execute'):
            # execute 메서드
            return await agent.execute(user_request, context)
        elif callable(agent):
            # 호출 가능한 객체
            return await agent(user_request)
        else:
            raise ValueError(f"에이전트 {agent_id}의 실행 방법을 알 수 없습니다.")
    
    async def _execute_handoff(self, negotiation_result: Dict[str, Any],
                             user_request: str, context: Dict[str, Any]) -> Any:
        """에이전트 핸드오프 실행"""
        target_agent = negotiation_result["selected_agent"]
        handoff_reason = negotiation_result.get("handoff_reason", "더 적합한 에이전트로 이관")
        
        logger.info(f"🔄 에이전트 핸드오프: {target_agent}")
        logger.info(f"   이관 사유: {handoff_reason}")
        
        # 핸드오프 컨텍스트 정보 추가
        enhanced_context = context.copy()
        enhanced_context["handoff_info"] = {
            "reason": handoff_reason,
            "original_request": user_request,
            "timestamp": time.time()
        }
        
        return await self._execute_single_agent(target_agent, user_request, enhanced_context)
    
    async def _execute_collaborative(self, negotiation_result: Dict[str, Any],
                                   user_request: str, context: Dict[str, Any]) -> Any:
        """협력 모드 실행"""
        participating_agents = negotiation_result.get("participating_agents", [])
        coordinator = negotiation_result.get("coordinator")
        
        logger.info(f"🤝 협력 모드 실행 ({len(participating_agents)}개 에이전트)")
        logger.info(f"   코디네이터: {coordinator}")
        logger.info(f"   참여 에이전트: {[agent['agent_id'] for agent in participating_agents]}")
        
        # 각 에이전트의 기여도에 따라 순차적으로 실행
        results = []
        
        for agent_info in participating_agents:
            agent_id = agent_info["agent_id"]
            role = agent_info.get("role", "collaborative")
            
            logger.info(f"   🤖 {agent_id} 실행 중 (역할: {role})...")
            
            try:
                # 이전 결과를 컨텍스트에 포함
                collaborative_context = context.copy()
                collaborative_context["collaborative_mode"] = True
                collaborative_context["previous_results"] = results
                collaborative_context["agent_role"] = role
                
                agent_result = await self._execute_single_agent(
                    agent_id, user_request, collaborative_context
                )
                
                results.append({
                    "agent_id": agent_id,
                    "role": role,
                    "result": agent_result,
                    "timestamp": time.time()
                })
                
                logger.info(f"   ✅ {agent_id} 완료")
                
            except Exception as e:
                logger.warning(f"   ⚠️ {agent_id} 실행 실패: {str(e)}")
                results.append({
                    "agent_id": agent_id,
                    "role": role,
                    "result": None,
                    "error": str(e),
                    "timestamp": time.time()
                })
        
        # 협력 결과 통합
        return {
            "mode": "collaborative",
            "coordinator": coordinator,
            "individual_results": results,
            "combined_result": self._combine_collaborative_results(results),
            "summary": f"{len(results)}개 에이전트가 협력하여 처리 완료"
        }
    
    def _combine_collaborative_results(self, results: List[Dict[str, Any]]) -> str:
        """협력 결과 통합"""
        successful_results = [r for r in results if r.get("result") is not None]
        
        if not successful_results:
            return "모든 에이전트 처리 실패"
        
        # 결과를 지능적으로 통합
        combined_text = []
        visualization_results = []
        data_results = []
        
        for result in successful_results:
            agent_id = result["agent_id"]
            result_content = result["result"]
            
            # AgentResponse 객체인 경우 처리
            if hasattr(result_content, 'content') and hasattr(result_content, 'type'):
                content = result_content.content
                
                # HTML 컨텐츠는 별도로 처리
                if isinstance(content, str) and content.strip().startswith("<!DOCTYPE html"):
                    visualization_results.append({
                        "agent_id": agent_id,
                        "type": "html_visualization",
                        "content": content
                    })
                    # HTML 대신 요약 정보 추가
                    combined_text.append(f"[{agent_id}] 시각화 생성 완료 (HTML 차트/다이어그램)")
                else:
                    # 일반 텍스트 결과
                    combined_text.append(f"[{agent_id}] {content}")
                    data_results.append({
                        "agent_id": agent_id,
                        "content": content
                    })
            else:
                # 일반 결과
                result_str = str(result_content)
                
                # HTML 문서인지 확인
                if result_str.strip().startswith("<!DOCTYPE html"):
                    visualization_results.append({
                        "agent_id": agent_id,
                        "type": "html_visualization",
                        "content": result_str
                    })
                    combined_text.append(f"[{agent_id}] 시각화 생성 완료 (HTML 차트/다이어그램)")
                else:
                    combined_text.append(f"[{agent_id}] {result_str}")
                    data_results.append({
                        "agent_id": agent_id,
                        "content": result_str
                    })
        
        # 결과 통합 - 더 깔끔한 포맷
        final_parts = []
        
        # 데이터 결과를 먼저 표시
        if data_results:
            for data in data_results:
                agent_name = data['agent_id'].replace('_', ' ').title()
                final_parts.append(f"### 📊 {agent_name} 결과\n\n{data['content']}")
        
        # 시각화 결과는 요약만 표시
        if visualization_results:
            viz_summary = "### 📈 시각화 생성 완료\n\n"
            for viz in visualization_results:
                agent_name = viz['agent_id'].replace('_', ' ').title()
                viz_summary += f"- {agent_name}: HTML 시각화 생성 완료\n"
            
            if len(visualization_results) > 0:
                viz_summary += "\n💡 시각화 결과는 별도의 HTML 뷰어에서 확인하실 수 있습니다."
            
            final_parts.append(viz_summary)
        
        # 최종 결과 조합
        if final_parts:
            return "\n\n---\n\n".join(final_parts)
        else:
            return "처리 결과가 없습니다."
    
    async def _execute_decomposed_plan(self, decomposition_plan, context: Dict[str, Any], 
                                     start_time: float) -> ProcessingResult:
        """분해된 작업 계획 실행"""
        logger.info(f"🚀 분해된 작업 실행 시작: {len(decomposition_plan.subtasks)}개 하위 작업")
        
        try:
            # 계획 실행
            execution_result = await self.task_decomposition_negotiator.execute_plan(decomposition_plan.id)
            
            # 결과 수집
            all_results = []
            participating_agents = []
            
            for subtask in decomposition_plan.subtasks:
                if subtask.assigned_agent:
                    participating_agents.append(subtask.assigned_agent)
                    
                subtask_result = execution_result["results"].get(subtask.id)
                if subtask_result:
                    all_results.append({
                        "subtask": subtask.description,
                        "agent": subtask.assigned_agent,
                        "result": subtask_result.get("result"),
                        "status": subtask_result.get("status")
                    })
            
            # 결과 통합
            combined_result = self._combine_decomposed_results(all_results, decomposition_plan)
            
            return ProcessingResult(
                success=True,
                result=combined_result,
                mode=ProcessingMode.DECOMPOSED,
                primary_agent=list(decomposition_plan.agent_assignments.keys())[0] if decomposition_plan.agent_assignments else "system",
                participating_agents=list(set(participating_agents)),
                processing_time=time.time() - start_time,
                negotiation_summary={
                    "decomposition_plan": {
                        "id": decomposition_plan.id,
                        "subtask_count": len(decomposition_plan.subtasks),
                        "complexity": decomposition_plan.overall_complexity.value,
                        "strategy": decomposition_plan.decomposition_strategy.value
                    },
                    "execution_time": execution_result.get("execution_time", 0)
                }
            )
            
        except Exception as e:
            logger.error(f"분해된 작업 실행 중 오류: {str(e)}")
            return ProcessingResult(
                success=False,
                result=None,
                mode=ProcessingMode.DECOMPOSED,
                primary_agent="system",
                participating_agents=[],
                processing_time=time.time() - start_time,
                negotiation_summary={"error": f"작업 실행 실패: {str(e)}"},
                error_message=str(e)
            )
    
    def _combine_decomposed_results(self, results: List[Dict[str, Any]], 
                                  plan: Any) -> Dict[str, Any]:
        """분해된 작업 결과 통합"""
        summary_parts = [
            f"## 작업 분해 실행 결과",
            f"원본 작업: {plan.original_task}",
            f"복잡도: {plan.overall_complexity.value}",
            f"전략: {plan.decomposition_strategy.value}",
            "",
            "### 하위 작업 결과:"
        ]
        
        for i, result in enumerate(results, 1):
            summary_parts.extend([
                f"\n{i}. **{result['subtask']}**",
                f"   - 담당: {result['agent']}",
                f"   - 상태: {result['status']}",
                f"   - 결과: {result['result']}"
            ])
        
        return {
            "summary": "\n".join(summary_parts),
            "detailed_results": results,
            "plan_id": plan.id,
            "success_rate": sum(1 for r in results if r['status'] == 'completed') / len(results) if results else 0
        }
    
    async def _update_performance_tracking(self, processing_result: ProcessingResult,
                                         negotiation_result: Dict[str, Any],
                                         total_time: float):
        """성능 추적 업데이트"""
        # 처리 이력 저장
        history_entry = {
            "timestamp": time.time(),
            "success": processing_result.success,
            "mode": processing_result.mode.value,
            "primary_agent": processing_result.primary_agent,
            "participating_agents": processing_result.participating_agents,
            "processing_time": processing_result.processing_time,
            "total_time": total_time,
            "negotiation_summary": processing_result.negotiation_summary
        }
        
        self.processing_history.append(history_entry)
        
        # 에이전트별 성능 통계 업데이트
        for agent_id in processing_result.participating_agents:
            if agent_id not in self.agent_performance:
                self.agent_performance[agent_id] = {
                    "total_requests": 0,
                    "successful_requests": 0,
                    "avg_processing_time": 0.0,
                    "success_rate": 0.0
                }
            
            stats = self.agent_performance[agent_id]
            stats["total_requests"] += 1
            
            if processing_result.success:
                stats["successful_requests"] += 1
            
            # 이동 평균으로 처리 시간 업데이트
            old_avg = stats["avg_processing_time"]
            new_time = processing_result.processing_time
            stats["avg_processing_time"] = (old_avg * 0.8) + (new_time * 0.2)
            
            # 성공률 업데이트
            stats["success_rate"] = stats["successful_requests"] / stats["total_requests"]
        
        logger.debug(f"📊 성능 추적 업데이트 완료")
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """성능 요약 조회"""
        total_requests = len(self.processing_history)
        successful_requests = sum(1 for h in self.processing_history if h["success"])
        
        mode_distribution = {}
        for history in self.processing_history:
            mode = history["mode"]
            mode_distribution[mode] = mode_distribution.get(mode, 0) + 1
        
        return {
            "total_requests": total_requests,
            "successful_requests": successful_requests,
            "success_rate": successful_requests / total_requests if total_requests > 0 else 0.0,
            "mode_distribution": mode_distribution,
            "agent_performance": self.agent_performance.copy(),
            "registered_agents": list(self.registered_agents.keys())
        }
    
    def get_agent_status(self) -> Dict[str, Any]:
        """에이전트 상태 조회"""
        return {
            "registered_count": len(self.registered_agents),
            "agents": {
                agent_id: {
                    "config": config,
                    "has_assessment": agent_id in self.agent_assessments,
                    "has_instance": agent_id in self.agent_instances,
                    "performance": self.agent_performance.get(agent_id, {})
                }
                for agent_id, config in self.registered_agents.items()
            }
        }

# 편의 함수들
async def create_advanced_manager(config: Dict[str, Any] = None) -> AdvancedMultiAgentManager:
    """Advanced Multi-Agent Manager 생성"""
    manager = AdvancedMultiAgentManager(config)
    logger.info("🤖 Advanced Multi-Agent Manager 생성 완료")
    return manager