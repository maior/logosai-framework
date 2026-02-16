"""
결과 기반 에이전트 선택기

기존 시스템과 호환되면서 결과 기반 평가를 통합하는 시스템
"""

import asyncio
import time
from typing import Dict, Any, List, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum
from loguru import logger

from .result_quality_evaluator import ResultQualityEvaluator, QualityScore, create_evaluation_request
from .multi_agent_trial_manager import MultiAgentTrialManager, TrialStrategy, AgentCandidate, TrialResult
from .agent_performance_tracker import AgentPerformanceTracker, QueryCategory
from .agent_types import AgentResponse, AgentResponseType


class SelectionMode(Enum):
    """선택 모드"""
    TRADITIONAL = "traditional"        # 기존 사전 평가 방식
    RESULT_BASED = "result_based"      # 결과 기반 평가 방식
    HYBRID = "hybrid"                  # 하이브리드 방식
    AUTO = "auto"                      # 자동 선택


@dataclass
class SelectionConfig:
    """선택 설정"""
    mode: SelectionMode = SelectionMode.HYBRID
    max_trials: int = 3
    quality_threshold: float = 0.7
    time_budget: float = 30.0
    trial_strategy: TrialStrategy = TrialStrategy.ADAPTIVE
    fallback_to_traditional: bool = True
    learning_enabled: bool = True


@dataclass
class SelectionResult:
    """선택 결과"""
    selected_agent_id: str
    result: Any
    quality_score: QualityScore
    selection_method: str
    trials_attempted: int
    total_time: float
    confidence: float
    metadata: Dict[str, Any]


class ResultBasedAgentSelector:
    """결과 기반 에이전트 선택기"""
    
    def __init__(self, llm_client, config: SelectionConfig = None):
        self.llm_client = llm_client
        self.config = config or SelectionConfig()
        
        # 핵심 컴포넌트들
        self.quality_evaluator = ResultQualityEvaluator(llm_client, {
            "min_score_threshold": self.config.quality_threshold,
            "evaluation_timeout": min(10.0, self.config.time_budget / 3)
        })
        
        self.trial_manager = MultiAgentTrialManager(self.quality_evaluator, {
            "default_strategy": self.config.trial_strategy.value,
            "max_trials": self.config.max_trials,
            "quality_threshold": self.config.quality_threshold,
            "time_budget": self.config.time_budget
        })
        
        self.performance_tracker = AgentPerformanceTracker({
            "learning_rate": 0.1,
            "max_records": 5000
        }) if self.config.learning_enabled else None
        
        # 기존 시스템 호환성
        self.traditional_selector = None  # 기존 선택기 참조
        
        # 통계
        self.selection_stats = {
            "total_selections": 0,
            "traditional_selections": 0,
            "result_based_selections": 0,
            "hybrid_selections": 0,
            "avg_selection_time": 0.0,
            "success_rate": 0.0
        }
        
        logger.info(f"🎯 결과 기반 에이전트 선택기 초기화 완료 (모드: {self.config.mode.value})")
    
    def set_traditional_selector(self, traditional_selector):
        """기존 선택기 설정 (호환성용)"""
        self.traditional_selector = traditional_selector
        logger.info("🔗 기존 선택기 연결 완료")
    
    def register_agent(self, agent_id: str, agent_instance: Any, 
                      priority: int = 0, metadata: Dict[str, Any] = None):
        """에이전트 등록"""
        
        # 성능 추적기에서 기존 성능 데이터 조회
        initial_success_rate = 0.5
        estimated_response_time = 5.0
        
        if self.performance_tracker:
            insights = self.performance_tracker.get_agent_insights(agent_id)
            if "overall_success_rate" in insights:
                initial_success_rate = insights["overall_success_rate"]
                estimated_response_time = insights["avg_execution_time"]
        
        # 시도 매니저에 등록
        self.trial_manager.register_agent(
            agent_id=agent_id,
            agent_instance=agent_instance,
            priority=priority,
            initial_success_rate=initial_success_rate,
            estimated_response_time=estimated_response_time
        )
        
        logger.info(f"📝 에이전트 등록: {agent_id}")
    
    async def select_and_execute(self, query: str, context: Dict[str, Any] = None,
                               available_agents: List[str] = None,
                               selection_mode: SelectionMode = None) -> SelectionResult:
        """
        에이전트 선택 및 실행
        
        Args:
            query: 사용자 쿼리
            context: 실행 컨텍스트
            available_agents: 사용 가능한 에이전트 목록
            selection_mode: 선택 모드 오버라이드
            
        Returns:
            SelectionResult: 선택 및 실행 결과
        """
        start_time = time.time()
        mode = selection_mode or self.config.mode
        
        try:
            logger.info(f"🎯 에이전트 선택 시작: {query[:50]}... (모드: {mode.value})")
            
            # 모드에 따른 선택 실행
            if mode == SelectionMode.TRADITIONAL:
                result = await self._execute_traditional_selection(query, context, available_agents)
            elif mode == SelectionMode.RESULT_BASED:
                result = await self._execute_result_based_selection(query, context, available_agents)
            elif mode == SelectionMode.HYBRID:
                result = await self._execute_hybrid_selection(query, context, available_agents)
            elif mode == SelectionMode.AUTO:
                result = await self._execute_auto_selection(query, context, available_agents)
            else:
                raise ValueError(f"지원하지 않는 선택 모드: {mode}")
            
            # 통계 업데이트
            self._update_selection_stats(result, mode, time.time() - start_time)
            
            # 성능 기록 (학습용)
            if self.performance_tracker and result:
                self.performance_tracker.record_performance(
                    agent_id=result.selected_agent_id,
                    query=query,
                    success=result.quality_score.overall_score >= self.config.quality_threshold,
                    quality_score=result.quality_score.overall_score,
                    execution_time=result.total_time
                )
            
            logger.info(f"✅ 에이전트 선택 완료: {result.selected_agent_id} (품질: {result.quality_score.overall_score:.2f})")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ 에이전트 선택 실패: {str(e)}")
            # 비상 대안 (기존 방식 또는 오류 응답)
            return await self._handle_selection_failure(query, context, str(e))
    
    async def _execute_traditional_selection(self, query: str, context: Dict[str, Any],
                                           available_agents: List[str]) -> SelectionResult:
        """기존 방식 선택 실행"""
        if not self.traditional_selector:
            raise ValueError("기존 선택기가 설정되지 않았습니다")
        
        # 기존 선택기 호출 (구현에 따라 조정 필요)
        selected_agent_id, agent_instance = await self.traditional_selector.select_agent(query, context)
        
        # 에이전트 실행
        start_time = time.time()
        result = await agent_instance.process(query, context)
        execution_time = time.time() - start_time
        
        # 품질 평가
        eval_request = create_evaluation_request(query, result, selected_agent_id, context)
        quality_score = await self.quality_evaluator.evaluate_result(eval_request)
        
        return SelectionResult(
            selected_agent_id=selected_agent_id,
            result=result,
            quality_score=quality_score,
            selection_method="traditional",
            trials_attempted=1,
            total_time=execution_time,
            confidence=0.8,  # 기존 방식 기본 신뢰도
            metadata={"fallback": False}
        )
    
    async def _execute_result_based_selection(self, query: str, context: Dict[str, Any],
                                            available_agents: List[str]) -> SelectionResult:
        """결과 기반 선택 실행"""
        
        # 다중 에이전트 시도 실행
        trial_result = await self.trial_manager.execute_trial_session(
            query=query,
            context=context,
            candidate_agents=available_agents,
            strategy=self.config.trial_strategy,
            max_trials=self.config.max_trials,
            quality_threshold=self.config.quality_threshold,
            time_budget=self.config.time_budget
        )
        
        if not trial_result:
            raise ValueError("모든 에이전트 시도 실패")
        
        return SelectionResult(
            selected_agent_id=trial_result.agent_id,
            result=trial_result.result,
            quality_score=trial_result.quality_score,
            selection_method="result_based",
            trials_attempted=trial_result.trial_order,
            total_time=trial_result.execution_time,
            confidence=trial_result.quality_score.confidence,
            metadata={"trial_strategy": self.config.trial_strategy.value}
        )
    
    async def _execute_hybrid_selection(self, query: str, context: Dict[str, Any],
                                      available_agents: List[str]) -> SelectionResult:
        """하이브리드 선택 실행"""
        
        # 1단계: 빠른 사전 필터링 (성능 추적기 활용)
        if self.performance_tracker:
            predicted_agents = self.performance_tracker.predict_best_agents(query, 3)
            if predicted_agents:
                # 예측된 에이전트들만 사용
                filtered_agents = [agent_id for agent_id, _ in predicted_agents]
                if available_agents:
                    filtered_agents = [a for a in filtered_agents if a in available_agents]
            else:
                filtered_agents = available_agents
        else:
            filtered_agents = available_agents
        
        # 2단계: 제한된 결과 기반 선택 (최대 2회 시도)
        limited_config = SelectionConfig(
            mode=SelectionMode.RESULT_BASED,
            max_trials=min(2, self.config.max_trials),
            quality_threshold=self.config.quality_threshold,
            time_budget=self.config.time_budget * 0.7,  # 시간 예산 70% 사용
            trial_strategy=TrialStrategy.BEST_FIRST
        )
        
        try:
            # 제한된 시도로 결과 기반 선택
            temp_manager = MultiAgentTrialManager(self.quality_evaluator, {
                "default_strategy": "best_first",
                "max_trials": limited_config.max_trials,
                "quality_threshold": limited_config.quality_threshold,
                "time_budget": limited_config.time_budget
            })
            
            # 필터링된 에이전트들 등록
            for agent_id in filtered_agents:
                if agent_id in self.trial_manager.agents:
                    candidate = self.trial_manager.agents[agent_id]
                    temp_manager.register_agent(
                        agent_id=candidate.agent_id,
                        agent_instance=candidate.agent_instance,
                        priority=candidate.priority,
                        initial_success_rate=candidate.success_rate,
                        estimated_response_time=candidate.avg_response_time
                    )
            
            trial_result = await temp_manager.execute_trial_session(
                query=query,
                context=context,
                strategy=TrialStrategy.BEST_FIRST,
                max_trials=limited_config.max_trials,
                quality_threshold=limited_config.quality_threshold,
                time_budget=limited_config.time_budget
            )
            
            if trial_result and trial_result.quality_score.overall_score >= self.config.quality_threshold:
                return SelectionResult(
                    selected_agent_id=trial_result.agent_id,
                    result=trial_result.result,
                    quality_score=trial_result.quality_score,
                    selection_method="hybrid",
                    trials_attempted=trial_result.trial_order,
                    total_time=trial_result.execution_time,
                    confidence=trial_result.quality_score.confidence,
                    metadata={"phase": "result_based", "filtered_agents": len(filtered_agents)}
                )
            
        except Exception as e:
            logger.warning(f"하이브리드 선택의 결과 기반 단계 실패: {e}")
        
        # 3단계: 기존 방식으로 폴백 (설정된 경우)
        if self.config.fallback_to_traditional and self.traditional_selector:
            logger.info("🔄 기존 방식으로 폴백")
            result = await self._execute_traditional_selection(query, context, available_agents)
            result.selection_method = "hybrid_fallback"
            result.metadata["phase"] = "traditional_fallback"
            return result
        
        raise ValueError("하이브리드 선택 실패")
    
    async def _execute_auto_selection(self, query: str, context: Dict[str, Any],
                                    available_agents: List[str]) -> SelectionResult:
        """자동 선택 실행 - 상황에 따라 최적 방식 선택"""
        
        # 상황 분석
        num_agents = len(available_agents) if available_agents else len(self.trial_manager.agents)
        query_complexity = len(query.split())
        time_budget = self.config.time_budget
        
        # 자동 모드 결정 로직
        if num_agents <= 1:
            # 에이전트가 1개면 바로 실행
            selected_mode = SelectionMode.TRADITIONAL
        elif time_budget < 5.0:
            # 시간이 부족하면 기존 방식
            selected_mode = SelectionMode.TRADITIONAL
        elif num_agents >= 5 and time_budget >= 20.0:
            # 에이전트가 많고 시간이 충분하면 결과 기반
            selected_mode = SelectionMode.RESULT_BASED
        else:
            # 일반적인 경우 하이브리드
            selected_mode = SelectionMode.HYBRID
        
        logger.info(f"🤖 자동 모드 선택: {selected_mode.value} (에이전트: {num_agents}, 시간: {time_budget}s)")
        
        # 선택된 모드로 실행
        result = await self.select_and_execute(query, context, available_agents, selected_mode)
        result.selection_method = f"auto_{selected_mode.value}"
        result.metadata["auto_selection_reason"] = {
            "num_agents": num_agents,
            "query_complexity": query_complexity,
            "time_budget": time_budget
        }
        
        return result
    
    async def _handle_selection_failure(self, query: str, context: Dict[str, Any], 
                                      error_msg: str) -> SelectionResult:
        """선택 실패 처리"""
        logger.error(f"에이전트 선택 실패 처리: {error_msg}")
        
        # 기본 오류 응답 생성
        error_response = AgentResponse(
            type=AgentResponseType.ERROR,
            content={
                "error": "에이전트 선택 실패",
                "message": "요청을 처리할 수 있는 적절한 에이전트를 찾을 수 없습니다.",
                "details": error_msg
            },
            metadata={"selection_failure": True}
        )
        
        # 기본 품질 점수
        from .result_quality_evaluator import QualityScore
        quality_score = QualityScore(
            overall_score=0.1,
            dimension_scores={},
            reasoning=[f"선택 실패: {error_msg}"],
            strengths=[],
            weaknesses=["에이전트 선택 불가"],
            confidence=0.1,
            evaluation_time=0.0
        )
        
        return SelectionResult(
            selected_agent_id="error_handler",
            result=error_response,
            quality_score=quality_score,
            selection_method="error_fallback",
            trials_attempted=0,
            total_time=0.0,
            confidence=0.1,
            metadata={"error": error_msg}
        )
    
    def _update_selection_stats(self, result: SelectionResult, mode: SelectionMode, selection_time: float):
        """선택 통계 업데이트"""
        self.selection_stats["total_selections"] += 1
        
        # 모드별 카운터
        if "traditional" in result.selection_method:
            self.selection_stats["traditional_selections"] += 1
        elif "result_based" in result.selection_method:
            self.selection_stats["result_based_selections"] += 1
        elif "hybrid" in result.selection_method:
            self.selection_stats["hybrid_selections"] += 1
        
        # 평균 시간 업데이트
        total = self.selection_stats["total_selections"]
        current_avg = self.selection_stats["avg_selection_time"]
        self.selection_stats["avg_selection_time"] = (
            (current_avg * (total - 1) + selection_time) / total
        )
        
        # 성공률 업데이트
        success = result.quality_score.overall_score >= self.config.quality_threshold
        current_success_rate = self.selection_stats["success_rate"]
        self.selection_stats["success_rate"] = (
            (current_success_rate * (total - 1) + (1.0 if success else 0.0)) / total
        )
    
    def get_selection_stats(self) -> Dict[str, Any]:
        """선택 통계 조회"""
        stats = self.selection_stats.copy()
        
        # 비율 계산
        total = stats["total_selections"]
        if total > 0:
            stats["traditional_ratio"] = stats["traditional_selections"] / total
            stats["result_based_ratio"] = stats["result_based_selections"] / total
            stats["hybrid_ratio"] = stats["hybrid_selections"] / total
        
        # 시스템 통계 추가
        if self.performance_tracker:
            stats["system_insights"] = self.performance_tracker.get_system_insights()
        
        return stats
    
    def get_recommendations(self) -> List[str]:
        """시스템 개선 추천"""
        recommendations = []
        
        stats = self.selection_stats
        
        # 성공률 기반 추천
        if stats["success_rate"] < 0.7:
            recommendations.append("전체 성공률이 낮습니다. 에이전트 품질 개선이나 품질 임계값 조정을 고려하세요.")
        
        # 응답 시간 기반 추천
        if stats["avg_selection_time"] > 15.0:
            recommendations.append("평균 선택 시간이 깁니다. 시간 예산 조정이나 FAST_FIRST 전략 사용을 고려하세요.")
        
        # 성능 추적기 추천
        if self.performance_tracker:
            tracker_suggestions = self.performance_tracker.suggest_improvements()
            recommendations.extend(tracker_suggestions)
        
        return recommendations


# 편의 함수들
def create_result_based_selector(llm_client, config: Dict[str, Any] = None) -> ResultBasedAgentSelector:
    """결과 기반 선택기 생성 편의 함수"""
    
    selection_config = SelectionConfig()
    if config:
        for key, value in config.items():
            if hasattr(selection_config, key):
                if key == "mode":
                    selection_config.mode = SelectionMode(value)
                elif key == "trial_strategy":
                    selection_config.trial_strategy = TrialStrategy(value)
                else:
                    setattr(selection_config, key, value)
    
    return ResultBasedAgentSelector(llm_client, selection_config)


if __name__ == "__main__":
    # 사용 예시
    async def test_result_based_selector():
        from logosai.utils.llm_client import LLMClient
        
        # LLM 클라이언트 생성
        llm_client = LLMClient(provider="google", model="gemini-2.5-flash-lite")
        await llm_client.initialize()
        
        # 선택기 생성
        selector = create_result_based_selector(llm_client, {
            "mode": "hybrid",
            "max_trials": 3,
            "quality_threshold": 0.7,
            "time_budget": 20.0
        })
        
        # 모의 에이전트들
        class MockAgent:
            def __init__(self, agent_id: str, quality: float):
                self.agent_id = agent_id
                self.quality = quality
            
            async def process(self, query: str, context=None):
                await asyncio.sleep(1)
                return {
                    "message": f"{self.agent_id}가 처리한 결과: {query}",
                    "quality_hint": self.quality
                }
        
        # 에이전트들 등록
        selector.register_agent("good_agent", MockAgent("good_agent", 0.9), priority=1)
        selector.register_agent("ok_agent", MockAgent("ok_agent", 0.6), priority=0)
        selector.register_agent("bad_agent", MockAgent("bad_agent", 0.3), priority=-1)
        
        # 선택 및 실행 테스트
        result = await selector.select_and_execute(
            query="테스트 쿼리입니다",
            context={"test": True}
        )
        
        logger.info(f"선택된 에이전트: {result.selected_agent_id}")
        logger.info(f"품질 점수: {result.quality_score.overall_score:.2f}")
        logger.info(f"선택 방법: {result.selection_method}")
        logger.info(f"시도 횟수: {result.trials_attempted}")

        # 통계 조회
        stats = selector.get_selection_stats()
        logger.info(f"선택 통계: {stats}")
    
    # 테스트 실행
    # asyncio.run(test_result_based_selector())