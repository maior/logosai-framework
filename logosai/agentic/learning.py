"""
AgenticLearning - 자율 학습 시스템

경험과 피드백을 통해 에이전트의 성능을 지속적으로 개선합니다.
"""

import asyncio
from typing import Dict, Any, List, Optional, Union, Tuple
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
from loguru import logger
import json
import statistics
from collections import defaultdict, deque


class LearningStrategy(Enum):
    """학습 전략"""
    REINFORCEMENT = "reinforcement"  # 강화 학습
    SUPERVISED = "supervised"  # 지도 학습
    UNSUPERVISED = "unsupervised"  # 비지도 학습
    TRANSFER = "transfer"  # 전이 학습
    CONTINUAL = "continual"  # 지속 학습
    META = "meta"  # 메타 학습


class FeedbackType(Enum):
    """피드백 타입"""
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    CORRECTIVE = "corrective"
    INFORMATIVE = "informative"


@dataclass
class Experience:
    """경험 데이터"""
    id: str
    action: str
    context: Dict[str, Any]
    result: Any
    reward: float  # -1.0 ~ 1.0
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if not self.id:
            import hashlib
            content = f"{self.action}{self.timestamp}"
            self.id = hashlib.md5(content.encode()).hexdigest()[:12]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "context": self.context,
            "result": self.result,
            "reward": self.reward,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }


@dataclass
class Feedback:
    """피드백 데이터"""
    type: FeedbackType
    content: str
    source: str  # user, system, self
    experience_id: Optional[str] = None
    suggestions: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "content": self.content,
            "source": self.source,
            "experience_id": self.experience_id,
            "suggestions": self.suggestions,
            "timestamp": self.timestamp.isoformat()
        }


@dataclass
class PerformanceMetrics:
    """성능 메트릭"""
    success_rate: float = 0.0
    average_reward: float = 0.0
    error_rate: float = 0.0
    response_time: float = 0.0
    learning_rate: float = 0.01
    confidence: float = 0.5
    total_experiences: int = 0
    successful_actions: int = 0
    failed_actions: int = 0
    
    def update(self, success: bool, reward: float, response_time: float):
        """메트릭 업데이트"""
        self.total_experiences += 1
        
        if success:
            self.successful_actions += 1
        else:
            self.failed_actions += 1
        
        # 성공률 업데이트
        self.success_rate = self.successful_actions / self.total_experiences
        self.error_rate = self.failed_actions / self.total_experiences
        
        # 평균 보상 업데이트 (이동 평균)
        alpha = 0.1  # 학습률
        self.average_reward = (1 - alpha) * self.average_reward + alpha * reward
        
        # 응답 시간 업데이트 (이동 평균)
        self.response_time = (1 - alpha) * self.response_time + alpha * response_time
        
        # 신뢰도 조정
        if success:
            self.confidence = min(1.0, self.confidence + 0.01)
        else:
            self.confidence = max(0.0, self.confidence - 0.02)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success_rate": self.success_rate,
            "average_reward": self.average_reward,
            "error_rate": self.error_rate,
            "response_time": self.response_time,
            "learning_rate": self.learning_rate,
            "confidence": self.confidence,
            "total_experiences": self.total_experiences,
            "successful_actions": self.successful_actions,
            "failed_actions": self.failed_actions
        }


class PolicyNetwork:
    """정책 네트워크 (간단한 구현)"""
    
    def __init__(self, learning_rate: float = 0.01):
        self.policy: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.learning_rate = learning_rate
        self.action_counts: Dict[str, int] = defaultdict(int)
    
    def get_action_value(self, state: str, action: str) -> float:
        """상태-행동 쌍의 가치 조회"""
        return self.policy[state][action]
    
    def update(self, state: str, action: str, reward: float):
        """정책 업데이트"""
        # Q-learning 스타일 업데이트
        old_value = self.policy[state][action]
        self.action_counts[action] += 1
        
        # 학습률을 시간에 따라 감소
        lr = self.learning_rate / (1 + self.action_counts[action] * 0.01)
        
        # 가치 업데이트
        self.policy[state][action] = old_value + lr * (reward - old_value)
    
    def get_best_action(self, state: str, available_actions: List[str]) -> str:
        """최적 행동 선택"""
        if not available_actions:
            return ""
        
        best_action = available_actions[0]
        best_value = self.get_action_value(state, best_action)
        
        for action in available_actions[1:]:
            value = self.get_action_value(state, action)
            if value > best_value:
                best_value = value
                best_action = action
        
        return best_action
    
    def explore_vs_exploit(self, state: str, available_actions: List[str], 
                          epsilon: float = 0.1) -> str:
        """탐색 vs 활용 전략"""
        import random
        
        if random.random() < epsilon:
            # 탐색: 무작위 행동 선택
            return random.choice(available_actions)
        else:
            # 활용: 최적 행동 선택
            return self.get_best_action(state, available_actions)


class AgenticLearning:
    """
    자율 학습 시스템
    
    경험과 피드백을 통해 에이전트의 행동과 의사결정을 개선합니다.
    """
    
    def __init__(self, strategy: LearningStrategy = LearningStrategy.REINFORCEMENT,
                 learning_rate: float = 0.01):
        """
        AgenticLearning 초기화
        
        Args:
            strategy: 학습 전략
            learning_rate: 학습률
        """
        self.strategy = strategy
        self.learning_rate = learning_rate
        
        # 경험 저장소
        self.experiences: deque = deque(maxlen=1000)
        self.feedback_history: List[Feedback] = []
        
        # 성능 메트릭
        self.metrics = PerformanceMetrics(learning_rate=learning_rate)
        
        # 정책 네트워크
        self.policy = PolicyNetwork(learning_rate)
        
        # 학습 패턴
        self.successful_patterns: Dict[str, List[str]] = defaultdict(list)
        self.failed_patterns: Dict[str, List[str]] = defaultdict(list)
        
        # 지식 베이스
        self.knowledge_base: Dict[str, Any] = {}
        
        logger.info(f"AgenticLearning initialized with {strategy.value} strategy")
    
    def record_experience(self, action: str, context: Dict[str, Any],
                         result: Any, reward: float) -> Experience:
        """경험 기록"""
        experience = Experience(
            id="",
            action=action,
            context=context,
            result=result,
            reward=reward
        )
        
        self.experiences.append(experience)
        
        # 메트릭 업데이트
        success = reward > 0
        self.metrics.update(success, reward, 0.1)  # response_time은 임시값
        
        # 패턴 기록
        pattern_key = self._extract_pattern(action, context)
        if success:
            self.successful_patterns[pattern_key].append(experience.id)
        else:
            self.failed_patterns[pattern_key].append(experience.id)
        
        logger.debug(f"Recorded experience: {experience.id} (reward: {reward})")
        return experience
    
    def learn_from_feedback(self, feedback: Feedback):
        """피드백으로부터 학습"""
        self.feedback_history.append(feedback)
        
        # 피드백 타입에 따른 처리
        if feedback.type == FeedbackType.POSITIVE:
            self._reinforce_positive(feedback)
        elif feedback.type == FeedbackType.NEGATIVE:
            self._penalize_negative(feedback)
        elif feedback.type == FeedbackType.CORRECTIVE:
            self._apply_correction(feedback)
        elif feedback.type == FeedbackType.INFORMATIVE:
            self._update_knowledge(feedback)
        
        logger.info(f"Learned from {feedback.type.value} feedback")
    
    def _reinforce_positive(self, feedback: Feedback):
        """긍정적 피드백 강화"""
        if feedback.experience_id:
            # 특정 경험 강화
            for exp in self.experiences:
                if exp.id == feedback.experience_id:
                    # 보상 증가
                    exp.reward = min(1.0, exp.reward + 0.1)
                    # 정책 업데이트
                    state = self._get_state_representation(exp.context)
                    self.policy.update(state, exp.action, exp.reward)
                    break
        
        # 신뢰도 증가
        self.metrics.confidence = min(1.0, self.metrics.confidence + 0.05)
    
    def _penalize_negative(self, feedback: Feedback):
        """부정적 피드백 처벌"""
        if feedback.experience_id:
            # 특정 경험 처벌
            for exp in self.experiences:
                if exp.id == feedback.experience_id:
                    # 보상 감소
                    exp.reward = max(-1.0, exp.reward - 0.1)
                    # 정책 업데이트
                    state = self._get_state_representation(exp.context)
                    self.policy.update(state, exp.action, exp.reward)
                    break
        
        # 신뢰도 감소
        self.metrics.confidence = max(0.0, self.metrics.confidence - 0.05)
    
    def _apply_correction(self, feedback: Feedback):
        """교정 피드백 적용"""
        # 제안사항을 지식 베이스에 추가
        for suggestion in feedback.suggestions:
            self.knowledge_base[f"correction_{len(self.knowledge_base)}"] = {
                "suggestion": suggestion,
                "context": feedback.content,
                "timestamp": feedback.timestamp
            }
        
        # 학습률 일시적 증가 (빠른 교정)
        old_lr = self.learning_rate
        self.learning_rate = min(0.1, self.learning_rate * 2)
        
        # 복구
        self.learning_rate = old_lr
    
    def _update_knowledge(self, feedback: Feedback):
        """정보성 피드백으로 지식 업데이트"""
        self.knowledge_base[f"info_{len(self.knowledge_base)}"] = {
            "content": feedback.content,
            "source": feedback.source,
            "timestamp": feedback.timestamp
        }
    
    def update_strategy(self, new_strategy: LearningStrategy = None):
        """학습 전략 업데이트"""
        if new_strategy:
            self.strategy = new_strategy
            logger.info(f"Learning strategy updated to: {new_strategy.value}")
        
        # 전략에 따른 파라미터 조정
        if self.strategy == LearningStrategy.REINFORCEMENT:
            self.learning_rate = 0.01
        elif self.strategy == LearningStrategy.SUPERVISED:
            self.learning_rate = 0.001
        elif self.strategy == LearningStrategy.META:
            self.learning_rate = 0.1
    
    def improve_performance(self) -> Dict[str, Any]:
        """성능 개선 분석 및 제안"""
        improvements = {
            "current_metrics": self.metrics.to_dict(),
            "suggestions": [],
            "patterns": {}
        }
        
        # 성공률이 낮은 경우
        if self.metrics.success_rate < 0.5:
            improvements["suggestions"].append(
                "성공률이 낮습니다. 더 많은 학습 데이터가 필요하거나 전략 변경을 고려하세요."
            )
        
        # 오류율이 높은 경우
        if self.metrics.error_rate > 0.3:
            improvements["suggestions"].append(
                "오류율이 높습니다. 실패 패턴을 분석하여 개선점을 찾으세요."
            )
        
        # 성공/실패 패턴 분석
        improvements["patterns"]["successful"] = list(self.successful_patterns.keys())[:5]
        improvements["patterns"]["failed"] = list(self.failed_patterns.keys())[:5]
        
        # 학습률 조정 제안
        if self.metrics.total_experiences > 100:
            if self.metrics.success_rate > 0.8:
                improvements["suggestions"].append(
                    "성능이 안정적입니다. 학습률을 낮춰 안정성을 높이세요."
                )
            elif self.metrics.success_rate < 0.3:
                improvements["suggestions"].append(
                    "성능이 낮습니다. 학습률을 높여 빠른 개선을 시도하세요."
                )
        
        return improvements
    
    def get_recommendation(self, state: Dict[str, Any], 
                          available_actions: List[str]) -> Tuple[str, float]:
        """현재 상태에서 최적 행동 추천"""
        state_repr = self._get_state_representation(state)
        
        # 탐색 vs 활용 전략 사용
        epsilon = 0.1 * (1.0 - self.metrics.confidence)  # 신뢰도가 높을수록 탐색 감소
        recommended_action = self.policy.explore_vs_exploit(
            state_repr, available_actions, epsilon
        )
        
        # 추천 신뢰도
        action_value = self.policy.get_action_value(state_repr, recommended_action)
        confidence = min(1.0, max(0.0, action_value + self.metrics.confidence) / 2)
        
        logger.debug(f"Recommended action: {recommended_action} (confidence: {confidence})")
        return recommended_action, confidence
    
    def _extract_pattern(self, action: str, context: Dict[str, Any]) -> str:
        """행동과 컨텍스트에서 패턴 추출"""
        # 간단한 패턴 추출
        context_keys = sorted(context.keys())[:3]  # 상위 3개 키만
        pattern = f"{action}::{':'.join(context_keys)}"
        return pattern
    
    def _get_state_representation(self, context: Dict[str, Any]) -> str:
        """상태 표현 생성"""
        # 컨텍스트를 문자열로 변환 (간단한 구현)
        key_values = []
        for key in sorted(context.keys())[:5]:  # 상위 5개 키만
            value = context[key]
            if isinstance(value, (str, int, float, bool)):
                key_values.append(f"{key}={value}")
        
        return "::".join(key_values) if key_values else "default"
    
    def transfer_learning(self, source_experiences: List[Experience]):
        """전이 학습 (다른 에이전트의 경험에서 학습)"""
        logger.info(f"Starting transfer learning with {len(source_experiences)} experiences")
        
        for exp in source_experiences:
            # 경험을 현재 에이전트에 맞게 조정
            adjusted_reward = exp.reward * 0.5  # 보수적으로 조정
            
            # 정책 업데이트
            state = self._get_state_representation(exp.context)
            self.policy.update(state, exp.action, adjusted_reward)
            
            # 패턴 학습
            pattern_key = self._extract_pattern(exp.action, exp.context)
            if adjusted_reward > 0:
                self.successful_patterns[pattern_key].append(f"transfer_{exp.id}")
        
        logger.info("Transfer learning completed")
    
    def get_learning_summary(self) -> Dict[str, Any]:
        """학습 요약 정보"""
        recent_rewards = [exp.reward for exp in list(self.experiences)[-10:]]
        
        return {
            "strategy": self.strategy.value,
            "metrics": self.metrics.to_dict(),
            "total_experiences": len(self.experiences),
            "total_feedback": len(self.feedback_history),
            "recent_average_reward": statistics.mean(recent_rewards) if recent_rewards else 0,
            "knowledge_base_size": len(self.knowledge_base),
            "successful_patterns": len(self.successful_patterns),
            "failed_patterns": len(self.failed_patterns),
            "policy_size": sum(len(actions) for actions in self.policy.policy.values())
        }
    
    def record_feedback(self, query: str, result: Dict[str, Any], 
                       feedback_type: FeedbackType, confidence: float):
        """피드백 기록 (호환성을 위한 메소드)
        
        Args:
            query: 사용자 쿼리
            result: 실행 결과
            feedback_type: 피드백 타입
            confidence: 신뢰도
        """
        # Feedback 객체 생성
        feedback = Feedback(
            type=feedback_type,
            content=f"Query: {query}, Result: {str(result)[:200]}",
            source="system"
        )
        
        # 기존 learn_from_feedback 메소드 호출
        self.learn_from_feedback(feedback)
        
        # 경험으로도 기록
        reward = confidence if feedback_type == FeedbackType.POSITIVE else -confidence
        experience = self.record_experience(
            action="process_query",
            context={"query": query, "confidence": confidence},
            result=result,
            reward=reward
        )
        
        logger.debug(f"Recorded feedback: {feedback_type.value} with confidence {confidence}")
        return experience

    def reset_learning(self):
        """학습 초기화"""
        self.experiences.clear()
        self.feedback_history.clear()
        self.metrics = PerformanceMetrics(learning_rate=self.learning_rate)
        self.policy = PolicyNetwork(self.learning_rate)
        self.successful_patterns.clear()
        self.failed_patterns.clear()
        self.knowledge_base.clear()
        
        logger.info("Learning system reset")