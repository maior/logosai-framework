"""
다중 에이전트 시도 매니저

여러 에이전트를 순차적으로 시도하여 최적의 결과를 찾는 시스템
"""

import asyncio
import time
from typing import Dict, Any, List, Optional, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger

from .result_quality_evaluator import (
    ResultQualityEvaluator, QualityScore, EvaluationRequest, create_evaluation_request
)
from .agent_types import AgentResponse, AgentResponseType


class TrialStrategy(Enum):
    """시도 전략"""
    FAST_FIRST = "fast_first"           # 빠른 에이전트부터
    BEST_FIRST = "best_first"           # 성공률 높은 에이전트부터
    PARALLEL_RACE = "parallel_race"     # 병렬 실행 후 가장 빠른 성공
    EXHAUSTIVE = "exhaustive"           # 모든 에이전트 시도 후 최고 선택
    ADAPTIVE = "adaptive"               # 상황에 따라 전략 선택


@dataclass
class AgentCandidate:
    """에이전트 후보"""
    agent_id: str
    agent_instance: Any
    priority: int = 0                   # 우선순위 (높을수록 먼저 시도)
    success_rate: float = 0.5           # 성공률 (0.0-1.0)
    avg_response_time: float = 5.0      # 평균 응답시간 (초)
    last_used: float = 0.0              # 마지막 사용 시간
    total_attempts: int = 0             # 총 시도 횟수
    successful_attempts: int = 0        # 성공 횟수


@dataclass
class TrialResult:
    """시도 결과"""
    agent_id: str
    result: Any
    quality_score: QualityScore
    execution_time: float
    trial_order: int                    # 시도 순서
    success: bool


@dataclass
class TrialSession:
    """시도 세션"""
    query: str
    context: Dict[str, Any]
    strategy: TrialStrategy
    max_trials: int = 3                 # 최대 시도 횟수
    quality_threshold: float = 0.7      # 품질 임계값
    time_budget: float = 30.0           # 시간 예산 (초)
    
    # 실행 상태
    start_time: float = field(default_factory=time.time)
    trials: List[TrialResult] = field(default_factory=list)
    best_result: Optional[TrialResult] = None
    completed: bool = False


class MultiAgentTrialManager:
    """다중 에이전트 시도 매니저"""
    
    def __init__(self, quality_evaluator: ResultQualityEvaluator, config: Dict[str, Any] = None):
        self.quality_evaluator = quality_evaluator
        self.config = config or {}
        
        # 설정값들
        self.default_strategy = TrialStrategy(self.config.get("default_strategy", "adaptive"))
        self.max_trials = self.config.get("max_trials", 3)
        self.quality_threshold = self.config.get("quality_threshold", 0.7)
        self.time_budget = self.config.get("time_budget", 30.0)
        self.parallel_timeout = self.config.get("parallel_timeout", 10.0)
        
        # 에이전트 관리
        self.agents: Dict[str, AgentCandidate] = {}
        self.active_sessions: Dict[str, TrialSession] = {}
        
        # 성능 메트릭
        self.total_sessions = 0
        self.successful_sessions = 0
        self.avg_trials_per_session = 0.0
        
        logger.info("🎯 다중 에이전트 시도 매니저 초기화 완료")
    
    def register_agent(self, agent_id: str, agent_instance: Any, 
                      priority: int = 0, initial_success_rate: float = 0.5,
                      estimated_response_time: float = 5.0):
        """에이전트 등록"""
        candidate = AgentCandidate(
            agent_id=agent_id,
            agent_instance=agent_instance,
            priority=priority,
            success_rate=initial_success_rate,
            avg_response_time=estimated_response_time
        )
        
        self.agents[agent_id] = candidate
        logger.info(f"📝 에이전트 등록: {agent_id} (우선순위: {priority}, 성공률: {initial_success_rate:.2f})")
    
    def unregister_agent(self, agent_id: str):
        """에이전트 등록 해제"""
        if agent_id in self.agents:
            del self.agents[agent_id]
            logger.info(f"🗑️ 에이전트 등록 해제: {agent_id}")
    
    async def execute_trial_session(self, query: str, context: Dict[str, Any] = None,
                                  strategy: TrialStrategy = None,
                                  candidate_agents: List[str] = None,
                                  max_trials: int = None,
                                  quality_threshold: float = None,
                                  time_budget: float = None) -> TrialResult:
        """
        시도 세션 실행
        
        Args:
            query: 사용자 쿼리
            context: 실행 컨텍스트
            strategy: 시도 전략
            candidate_agents: 후보 에이전트 목록 (None이면 모든 등록된 에이전트)
            max_trials: 최대 시도 횟수
            quality_threshold: 품질 임계값
            time_budget: 시간 예산
            
        Returns:
            TrialResult: 최종 선택된 결과
        """
        session_id = f"session_{int(time.time() * 1000)}"
        
        # 세션 설정
        session = TrialSession(
            query=query,
            context=context or {},
            strategy=strategy or self.default_strategy,
            max_trials=max_trials or self.max_trials,
            quality_threshold=quality_threshold or self.quality_threshold,
            time_budget=time_budget or self.time_budget
        )
        
        self.active_sessions[session_id] = session
        self.total_sessions += 1
        
        try:
            logger.info(f"🚀 시도 세션 시작: {session_id} (전략: {session.strategy.value})")
            
            # 후보 에이전트 선정
            candidates = self._select_candidates(candidate_agents, query, context)
            
            if not candidates:
                raise ValueError("사용 가능한 에이전트가 없습니다")
            
            # 전략에 따른 실행
            if session.strategy == TrialStrategy.FAST_FIRST:
                result = await self._execute_fast_first_strategy(session, candidates)
            elif session.strategy == TrialStrategy.BEST_FIRST:
                result = await self._execute_best_first_strategy(session, candidates)
            elif session.strategy == TrialStrategy.PARALLEL_RACE:
                result = await self._execute_parallel_race_strategy(session, candidates)
            elif session.strategy == TrialStrategy.EXHAUSTIVE:
                result = await self._execute_exhaustive_strategy(session, candidates)
            elif session.strategy == TrialStrategy.ADAPTIVE:
                result = await self._execute_adaptive_strategy(session, candidates)
            else:
                # 기본값으로 BEST_FIRST 사용
                result = await self._execute_best_first_strategy(session, candidates)
            
            session.best_result = result
            session.completed = True
            
            if result and result.success:
                self.successful_sessions += 1
            
            # 성능 통계 업데이트
            self._update_performance_stats(session)
            
            logger.info(f"✅ 시도 세션 완료: {session_id} (결과: {result.agent_id if result else 'None'})")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ 시도 세션 실패: {session_id} - {str(e)}")
            raise
        finally:
            # 세션 정리
            if session_id in self.active_sessions:
                del self.active_sessions[session_id]
    
    def _select_candidates(self, candidate_list: List[str], query: str, context: Dict[str, Any]) -> List[AgentCandidate]:
        """후보 에이전트 선정"""
        if candidate_list:
            # 지정된 후보들만 사용
            candidates = [self.agents[agent_id] for agent_id in candidate_list if agent_id in self.agents]
        else:
            # 모든 등록된 에이전트 사용
            candidates = list(self.agents.values())
        
        # 빠른 사전 필터링 (기본적인 키워드 매칭)
        filtered_candidates = []
        for candidate in candidates:
            # 여기에 간단한 사전 필터링 로직 추가 가능
            # 예: 쿼리에 "계산"이 있으면 calculator_agent 우선
            filtered_candidates.append(candidate)
        
        return filtered_candidates
    
    async def _execute_fast_first_strategy(self, session: TrialSession, 
                                         candidates: List[AgentCandidate]) -> Optional[TrialResult]:
        """빠른 에이전트 우선 전략"""
        # 응답시간 기준으로 정렬
        sorted_candidates = sorted(candidates, key=lambda x: x.avg_response_time)
        
        for i, candidate in enumerate(sorted_candidates[:session.max_trials]):
            if self._is_time_budget_exceeded(session):
                break
                
            result = await self._try_single_agent(session, candidate, i + 1)
            if result and result.quality_score.overall_score >= session.quality_threshold:
                return result
        
        # 임계값을 넘는 결과가 없으면 가장 좋은 결과 반환
        return self._get_best_trial_result(session)
    
    async def _execute_best_first_strategy(self, session: TrialSession, 
                                         candidates: List[AgentCandidate]) -> Optional[TrialResult]:
        """성공률 높은 에이전트 우선 전략"""
        # 성공률과 우선순위 기준으로 정렬
        sorted_candidates = sorted(candidates, 
                                 key=lambda x: (x.priority, x.success_rate), 
                                 reverse=True)
        
        for i, candidate in enumerate(sorted_candidates[:session.max_trials]):
            if self._is_time_budget_exceeded(session):
                break
                
            result = await self._try_single_agent(session, candidate, i + 1)
            if result and result.quality_score.overall_score >= session.quality_threshold:
                return result
        
        return self._get_best_trial_result(session)
    
    async def _execute_parallel_race_strategy(self, session: TrialSession, 
                                            candidates: List[AgentCandidate]) -> Optional[TrialResult]:
        """병렬 경주 전략 - 가장 빠른 성공 결과 선택"""
        # 최대 3개까지 병렬 실행
        parallel_candidates = candidates[:min(3, len(candidates))]
        
        # 병렬 태스크 생성
        tasks = []
        for i, candidate in enumerate(parallel_candidates):
            task = asyncio.create_task(
                self._try_single_agent_with_timeout(session, candidate, i + 1, self.parallel_timeout)
            )
            tasks.append(task)
        
        try:
            # 첫 번째 성공 결과를 기다림
            for completed_task in asyncio.as_completed(tasks):
                result = await completed_task
                if result and result.quality_score.overall_score >= session.quality_threshold:
                    # 다른 태스크들 취소
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    return result
            
            # 모든 결과를 기다리고 최고 결과 선택
            results = await asyncio.gather(*tasks, return_exceptions=True)
            valid_results = [r for r in results if isinstance(r, TrialResult)]
            
            if valid_results:
                return max(valid_results, key=lambda x: x.quality_score.overall_score)
            
        except Exception as e:
            logger.error(f"병렬 실행 중 오류: {e}")
        
        return None
    
    async def _execute_exhaustive_strategy(self, session: TrialSession, 
                                         candidates: List[AgentCandidate]) -> Optional[TrialResult]:
        """전체 탐색 전략 - 모든 에이전트 시도 후 최고 선택"""
        # 우선순위 기준으로 정렬
        sorted_candidates = sorted(candidates, key=lambda x: x.priority, reverse=True)
        
        for i, candidate in enumerate(sorted_candidates):
            if self._is_time_budget_exceeded(session):
                break
                
            await self._try_single_agent(session, candidate, i + 1)
        
        return self._get_best_trial_result(session)
    
    async def _execute_adaptive_strategy(self, session: TrialSession, 
                                       candidates: List[AgentCandidate]) -> Optional[TrialResult]:
        """적응적 전략 - 상황에 따라 최적 전략 선택"""
        num_candidates = len(candidates)
        query_length = len(session.query.split())
        
        # 상황별 전략 선택
        if num_candidates <= 2:
            # 후보가 적으면 전체 탐색
            return await self._execute_exhaustive_strategy(session, candidates)
        elif query_length < 5:
            # 간단한 쿼리면 빠른 에이전트 우선
            return await self._execute_fast_first_strategy(session, candidates)
        elif session.time_budget < 10.0:
            # 시간이 부족하면 병렬 경주
            return await self._execute_parallel_race_strategy(session, candidates)
        else:
            # 일반적인 경우 성공률 우선
            return await self._execute_best_first_strategy(session, candidates)
    
    async def _try_single_agent(self, session: TrialSession, candidate: AgentCandidate, 
                               trial_order: int) -> Optional[TrialResult]:
        """단일 에이전트 시도"""
        start_time = time.time()
        
        try:
            logger.info(f"🔍 에이전트 시도 {trial_order}: {candidate.agent_id}")
            
            # 에이전트 실행
            if hasattr(candidate.agent_instance, 'process'):
                agent_result = await candidate.agent_instance.process(session.query, session.context)
            else:
                raise ValueError(f"에이전트 {candidate.agent_id}에 process 메서드가 없습니다")
            
            execution_time = time.time() - start_time
            
            # 결과 품질 평가
            eval_request = create_evaluation_request(
                query=session.query,
                result=agent_result,
                agent_id=candidate.agent_id,
                context=session.context
            )
            
            quality_score = await self.quality_evaluator.evaluate_result(eval_request)
            
            # 시도 결과 생성
            trial_result = TrialResult(
                agent_id=candidate.agent_id,
                result=agent_result,
                quality_score=quality_score,
                execution_time=execution_time,
                trial_order=trial_order,
                success=quality_score.overall_score >= session.quality_threshold
            )
            
            session.trials.append(trial_result)
            
            # 에이전트 통계 업데이트
            self._update_agent_stats(candidate, trial_result)
            
            logger.info(f"✅ 에이전트 시도 완료: {candidate.agent_id} (품질: {quality_score.overall_score:.2f})")
            
            return trial_result
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"❌ 에이전트 시도 실패: {candidate.agent_id} - {str(e)}")
            
            # 실패도 통계에 반영
            candidate.total_attempts += 1
            candidate.avg_response_time = (candidate.avg_response_time + execution_time) / 2
            
            return None
    
    async def _try_single_agent_with_timeout(self, session: TrialSession, candidate: AgentCandidate, 
                                           trial_order: int, timeout: float) -> Optional[TrialResult]:
        """타임아웃이 있는 단일 에이전트 시도"""
        try:
            return await asyncio.wait_for(
                self._try_single_agent(session, candidate, trial_order),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"⏰ 에이전트 시도 타임아웃: {candidate.agent_id}")
            return None
    
    def _is_time_budget_exceeded(self, session: TrialSession) -> bool:
        """시간 예산 초과 여부 확인"""
        elapsed = time.time() - session.start_time
        return elapsed >= session.time_budget
    
    def _get_best_trial_result(self, session: TrialSession) -> Optional[TrialResult]:
        """세션에서 가장 좋은 결과 반환"""
        if not session.trials:
            return None
        
        # 품질 점수 기준으로 최고 결과 선택
        return max(session.trials, key=lambda x: x.quality_score.overall_score)
    
    def _update_agent_stats(self, candidate: AgentCandidate, trial_result: TrialResult):
        """에이전트 통계 업데이트"""
        candidate.total_attempts += 1
        candidate.last_used = time.time()
        
        if trial_result.success:
            candidate.successful_attempts += 1
        
        # 성공률 업데이트
        candidate.success_rate = candidate.successful_attempts / candidate.total_attempts
        
        # 평균 응답시간 업데이트 (지수 이동평균)
        alpha = 0.3  # 학습률
        candidate.avg_response_time = (
            alpha * trial_result.execution_time + 
            (1 - alpha) * candidate.avg_response_time
        )
    
    def _update_performance_stats(self, session: TrialSession):
        """전체 성능 통계 업데이트"""
        num_trials = len(session.trials)
        self.avg_trials_per_session = (
            (self.avg_trials_per_session * (self.total_sessions - 1) + num_trials) / 
            self.total_sessions
        )
    
    def get_agent_stats(self, agent_id: str) -> Dict[str, Any]:
        """특정 에이전트 통계 조회"""
        if agent_id not in self.agents:
            return {}
        
        candidate = self.agents[agent_id]
        return {
            "agent_id": agent_id,
            "success_rate": candidate.success_rate,
            "avg_response_time": candidate.avg_response_time,
            "total_attempts": candidate.total_attempts,
            "successful_attempts": candidate.successful_attempts,
            "last_used": candidate.last_used
        }
    
    def get_system_stats(self) -> Dict[str, Any]:
        """시스템 전체 통계"""
        success_rate = self.successful_sessions / max(self.total_sessions, 1)
        
        return {
            "total_sessions": self.total_sessions,
            "successful_sessions": self.successful_sessions,
            "success_rate": success_rate,
            "avg_trials_per_session": self.avg_trials_per_session,
            "registered_agents": len(self.agents),
            "active_sessions": len(self.active_sessions)
        }
    
    def get_top_performing_agents(self, limit: int = 5) -> List[Dict[str, Any]]:
        """성능이 좋은 상위 에이전트 목록"""
        sorted_agents = sorted(
            self.agents.values(),
            key=lambda x: (x.success_rate, -x.avg_response_time),
            reverse=True
        )
        
        return [
            {
                "agent_id": agent.agent_id,
                "success_rate": agent.success_rate,
                "avg_response_time": agent.avg_response_time,
                "total_attempts": agent.total_attempts
            }
            for agent in sorted_agents[:limit]
        ]


# 편의 함수들
def create_trial_manager(llm_client, config: Dict[str, Any] = None) -> MultiAgentTrialManager:
    """시도 매니저 생성 편의 함수"""
    from .result_quality_evaluator import ResultQualityEvaluator
    
    evaluator_config = config.get("evaluator", {}) if config else {}
    quality_evaluator = ResultQualityEvaluator(llm_client, evaluator_config)
    
    manager_config = config.get("manager", {}) if config else {}
    return MultiAgentTrialManager(quality_evaluator, manager_config)


if __name__ == "__main__":
    # 사용 예시
    async def test_trial_manager():
        from logosai.utils.llm_client import LLMClient
        
        # LLM 클라이언트 생성
        llm_client = LLMClient(provider="google", model="gemini-2.5-flash-lite")
        await llm_client.initialize()
        
        # 시도 매니저 생성
        manager = create_trial_manager(llm_client, {
            "manager": {
                "default_strategy": "best_first",
                "max_trials": 3,
                "quality_threshold": 0.7
            }
        })
        
        # 모의 에이전트들 등록
        class MockAgent:
            def __init__(self, agent_id: str, quality: float):
                self.agent_id = agent_id
                self.quality = quality
            
            async def process(self, query: str, context=None):
                await asyncio.sleep(1)  # 모의 처리 시간
                return {
                    "message": f"{self.agent_id}가 처리한 결과: {query}",
                    "quality": self.quality
                }
        
        # 에이전트들 등록
        agents = [
            ("good_agent", MockAgent("good_agent", 0.9), 1, 0.8),
            ("ok_agent", MockAgent("ok_agent", 0.6), 0, 0.6),
            ("bad_agent", MockAgent("bad_agent", 0.3), -1, 0.3)
        ]
        
        for agent_id, agent_instance, priority, success_rate in agents:
            manager.register_agent(agent_id, agent_instance, priority, success_rate)
        
        # 테스트 쿼리 실행
        result = await manager.execute_trial_session(
            query="테스트 계산을 해주세요",
            strategy=TrialStrategy.BEST_FIRST
        )
        
        print(f"최종 선택된 에이전트: {result.agent_id if result else 'None'}")
        print(f"품질 점수: {result.quality_score.overall_score if result else 'N/A'}")
        
        # 통계 조회
        stats = manager.get_system_stats()
        print(f"시스템 통계: {stats}")
    
    # 테스트 실행
    # asyncio.run(test_trial_manager())