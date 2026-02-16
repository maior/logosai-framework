"""
에이전트 성능 추적 및 학습 시스템

에이전트들의 성능을 지속적으로 모니터링하고 패턴을 학습하여
미래의 에이전트 선택을 최적화하는 시스템
"""

import asyncio
import json
import time
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict, deque
from enum import Enum
from loguru import logger


class QueryCategory(Enum):
    """쿼리 카테고리"""
    CALCULATION = "calculation"
    TEXT_PROCESSING = "text_processing"
    DATA_ANALYSIS = "data_analysis"
    CODE_GENERATION = "code_generation"
    TRANSLATION = "translation"
    SEARCH = "search"
    GENERAL = "general"
    UNKNOWN = "unknown"


@dataclass
class PerformanceRecord:
    """성능 기록"""
    timestamp: float
    agent_id: str
    query: str
    query_category: QueryCategory
    query_hash: str                     # 개인정보 보호용
    success: bool
    quality_score: float
    execution_time: float
    error_type: Optional[str] = None
    user_feedback: Optional[float] = None  # 사용자 피드백 (0-1)


@dataclass
class AgentPerformanceProfile:
    """에이전트 성능 프로필"""
    agent_id: str
    total_attempts: int = 0
    successful_attempts: int = 0
    avg_quality_score: float = 0.5
    avg_execution_time: float = 5.0
    category_performance: Dict[str, Dict[str, float]] = field(default_factory=dict)
    recent_performance: deque = field(default_factory=lambda: deque(maxlen=100))
    performance_trend: List[float] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)
    
    def __post_init__(self):
        if isinstance(self.recent_performance, list):
            self.recent_performance = deque(self.recent_performance, maxlen=100)


@dataclass
class QueryPattern:
    """쿼리 패턴"""
    pattern_id: str
    keywords: List[str]
    category: QueryCategory
    best_agents: List[Tuple[str, float]]  # (agent_id, success_rate)
    total_queries: int = 0
    avg_quality: float = 0.0


class AgentPerformanceTracker:
    """에이전트 성능 추적기"""
    
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        
        # 설정값들
        self.max_records = self.config.get("max_records", 10000)
        self.learning_rate = self.config.get("learning_rate", 0.1)
        self.pattern_threshold = self.config.get("pattern_threshold", 10)  # 패턴 인식 최소 샘플 수
        
        # 데이터 저장소
        self.performance_records: List[PerformanceRecord] = []
        self.agent_profiles: Dict[str, AgentPerformanceProfile] = {}
        self.query_patterns: Dict[str, QueryPattern] = {}
        self.category_agents: Dict[QueryCategory, List[Tuple[str, float]]] = defaultdict(list)
        
        # 학습된 지식
        self.learned_preferences: Dict[str, Dict[str, float]] = defaultdict(dict)
        self.failure_patterns: Dict[str, List[str]] = defaultdict(list)
        
        # 성능 메트릭
        self.prediction_accuracy = 0.0
        self.learning_iterations = 0
        
        logger.info("📊 에이전트 성능 추적기 초기화 완료")
    
    def record_performance(self, agent_id: str, query: str, success: bool,
                          quality_score: float, execution_time: float,
                          error_type: Optional[str] = None,
                          user_feedback: Optional[float] = None):
        """성능 기록 추가"""
        
        # 쿼리 카테고리 분류
        query_category = self._classify_query(query)
        
        # 쿼리 해시 (개인정보 보호)
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
        
        # 성능 기록 생성
        record = PerformanceRecord(
            timestamp=time.time(),
            agent_id=agent_id,
            query=query[:100],  # 일부만 저장
            query_category=query_category,
            query_hash=query_hash,
            success=success,
            quality_score=quality_score,
            execution_time=execution_time,
            error_type=error_type,
            user_feedback=user_feedback
        )
        
        # 기록 저장
        self.performance_records.append(record)
        
        # 최대 기록 수 제한
        if len(self.performance_records) > self.max_records:
            self.performance_records = self.performance_records[-self.max_records:]
        
        # 에이전트 프로필 업데이트
        self._update_agent_profile(agent_id, record)
        
        # 패턴 학습
        self._update_patterns(record)
        
        logger.debug(f"📝 성능 기록 추가: {agent_id} (성공: {success}, 품질: {quality_score:.2f})")
    
    def _classify_query(self, query: str) -> QueryCategory:
        """쿼리 카테고리 분류"""
        query_lower = query.lower()
        
        # 키워드 기반 분류
        calculation_keywords = ["계산", "더하기", "빼기", "곱하기", "나누기", "+", "-", "*", "/", "수학"]
        text_keywords = ["요약", "번역", "교정", "맞춤법", "문서", "텍스트"]
        data_keywords = ["분석", "통계", "데이터", "차트", "그래프", "시각화"]
        code_keywords = ["코드", "프로그래밍", "함수", "변수", "클래스", "python", "javascript"]
        translation_keywords = ["번역", "translate", "영어", "한국어", "언어"]
        search_keywords = ["검색", "찾기", "search", "find", "lookup"]
        
        if any(keyword in query_lower for keyword in calculation_keywords):
            return QueryCategory.CALCULATION
        elif any(keyword in query_lower for keyword in text_keywords):
            return QueryCategory.TEXT_PROCESSING
        elif any(keyword in query_lower for keyword in data_keywords):
            return QueryCategory.DATA_ANALYSIS
        elif any(keyword in query_lower for keyword in code_keywords):
            return QueryCategory.CODE_GENERATION
        elif any(keyword in query_lower for keyword in translation_keywords):
            return QueryCategory.TRANSLATION
        elif any(keyword in query_lower for keyword in search_keywords):
            return QueryCategory.SEARCH
        else:
            return QueryCategory.GENERAL
    
    def _update_agent_profile(self, agent_id: str, record: PerformanceRecord):
        """에이전트 프로필 업데이트"""
        if agent_id not in self.agent_profiles:
            self.agent_profiles[agent_id] = AgentPerformanceProfile(agent_id=agent_id)
        
        profile = self.agent_profiles[agent_id]
        
        # 기본 통계 업데이트
        profile.total_attempts += 1
        if record.success:
            profile.successful_attempts += 1
        
        # 지수 이동평균으로 품질 점수 업데이트
        alpha = self.learning_rate
        profile.avg_quality_score = (
            alpha * record.quality_score + 
            (1 - alpha) * profile.avg_quality_score
        )
        
        # 실행 시간 업데이트
        profile.avg_execution_time = (
            alpha * record.execution_time + 
            (1 - alpha) * profile.avg_execution_time
        )
        
        # 카테고리별 성능 업데이트
        category = record.query_category.value
        if category not in profile.category_performance:
            profile.category_performance[category] = {
                "attempts": 0,
                "successes": 0,
                "avg_quality": 0.5,
                "avg_time": 5.0
            }
        
        cat_perf = profile.category_performance[category]
        cat_perf["attempts"] += 1
        if record.success:
            cat_perf["successes"] += 1
        
        cat_perf["avg_quality"] = (
            alpha * record.quality_score + 
            (1 - alpha) * cat_perf["avg_quality"]
        )
        cat_perf["avg_time"] = (
            alpha * record.execution_time + 
            (1 - alpha) * cat_perf["avg_time"]
        )
        
        # 최근 성능 기록
        profile.recent_performance.append({
            "timestamp": record.timestamp,
            "success": record.success,
            "quality": record.quality_score,
            "time": record.execution_time
        })
        
        # 성능 트렌드 업데이트 (최근 10개 기록의 평균)
        if len(profile.recent_performance) >= 10:
            recent_quality = sum(r["quality"] for r in list(profile.recent_performance)[-10:]) / 10
            profile.performance_trend.append(recent_quality)
            
            # 트렌드 길이 제한
            if len(profile.performance_trend) > 100:
                profile.performance_trend = profile.performance_trend[-100:]
        
        profile.last_updated = time.time()
    
    def _update_patterns(self, record: PerformanceRecord):
        """쿼리 패턴 학습 업데이트"""
        # 카테고리별 에이전트 성능 업데이트
        category = record.query_category
        
        # 기존 에이전트 찾기
        found = False
        for i, (agent_id, success_rate) in enumerate(self.category_agents[category]):
            if agent_id == record.agent_id:
                # 성공률 업데이트 (지수 이동평균)
                new_success = 1.0 if record.success else 0.0
                updated_rate = self.learning_rate * new_success + (1 - self.learning_rate) * success_rate
                self.category_agents[category][i] = (agent_id, updated_rate)
                found = True
                break
        
        if not found:
            # 새 에이전트 추가
            initial_rate = 1.0 if record.success else 0.0
            self.category_agents[category].append((record.agent_id, initial_rate))
        
        # 성공률 기준으로 정렬
        self.category_agents[category].sort(key=lambda x: x[1], reverse=True)
    
    def predict_best_agents(self, query: str, num_agents: int = 3) -> List[Tuple[str, float]]:
        """쿼리에 대한 최적 에이전트 예측"""
        
        # 쿼리 카테고리 분류
        category = self._classify_query(query)
        
        # 카테고리별 추천 에이전트
        category_agents = self.category_agents.get(category, [])
        
        # 전체 에이전트 성능도 고려
        all_agents_performance = []
        for agent_id, profile in self.agent_profiles.items():
            overall_score = self._calculate_overall_score(profile, category)
            all_agents_performance.append((agent_id, overall_score))
        
        # 두 점수를 결합 (가중평균)
        combined_scores = {}
        
        # 카테고리 특화 점수 (가중치 0.7)
        for agent_id, score in category_agents:
            combined_scores[agent_id] = score * 0.7
        
        # 전체 성능 점수 (가중치 0.3)
        for agent_id, score in all_agents_performance:
            if agent_id in combined_scores:
                combined_scores[agent_id] += score * 0.3
            else:
                combined_scores[agent_id] = score * 0.3
        
        # 점수 기준으로 정렬
        sorted_agents = sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)
        
        return sorted_agents[:num_agents]
    
    def _calculate_overall_score(self, profile: AgentPerformanceProfile, category: QueryCategory) -> float:
        """에이전트의 전체 성능 점수 계산"""
        if profile.total_attempts == 0:
            return 0.5
        
        # 기본 성공률
        success_rate = profile.successful_attempts / profile.total_attempts
        
        # 품질 점수
        quality_score = profile.avg_quality_score
        
        # 속도 점수 (빠를수록 좋음, 최대 30초 기준)
        speed_score = max(0, (30 - profile.avg_execution_time) / 30)
        
        # 카테고리 특화 점수
        category_score = 0.5
        if category.value in profile.category_performance:
            cat_perf = profile.category_performance[category.value]
            if cat_perf["attempts"] > 0:
                category_score = cat_perf["successes"] / cat_perf["attempts"]
        
        # 최근 성능 트렌드
        trend_score = 0.5
        if len(profile.performance_trend) >= 3:
            recent_trend = profile.performance_trend[-3:]
            trend_score = sum(recent_trend) / len(recent_trend)
        
        # 가중 평균
        overall_score = (
            success_rate * 0.3 +
            quality_score * 0.25 +
            speed_score * 0.15 +
            category_score * 0.2 +
            trend_score * 0.1
        )
        
        return min(1.0, max(0.0, overall_score))
    
    def get_agent_insights(self, agent_id: str) -> Dict[str, Any]:
        """에이전트 인사이트 조회"""
        if agent_id not in self.agent_profiles:
            return {"error": "에이전트를 찾을 수 없습니다"}
        
        profile = self.agent_profiles[agent_id]
        
        # 강점/약점 분석
        strengths = []
        weaknesses = []
        
        for category, perf in profile.category_performance.items():
            if perf["attempts"] >= 5:  # 충분한 데이터가 있는 경우만
                success_rate = perf["successes"] / perf["attempts"]
                if success_rate >= 0.8:
                    strengths.append(f"{category} 처리 (성공률: {success_rate:.1%})")
                elif success_rate <= 0.3:
                    weaknesses.append(f"{category} 처리 (성공률: {success_rate:.1%})")
        
        # 성능 트렌드 분석
        trend_analysis = "안정적"
        if len(profile.performance_trend) >= 5:
            recent = profile.performance_trend[-5:]
            if recent[-1] > recent[0]:
                trend_analysis = "향상 중"
            elif recent[-1] < recent[0]:
                trend_analysis = "하락 중"
        
        return {
            "agent_id": agent_id,
            "overall_success_rate": profile.successful_attempts / max(profile.total_attempts, 1),
            "avg_quality_score": profile.avg_quality_score,
            "avg_execution_time": profile.avg_execution_time,
            "total_attempts": profile.total_attempts,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "trend_analysis": trend_analysis,
            "category_performance": profile.category_performance,
            "last_updated": profile.last_updated
        }
    
    def get_system_insights(self) -> Dict[str, Any]:
        """시스템 전체 인사이트"""
        total_records = len(self.performance_records)
        
        if total_records == 0:
            return {"message": "성능 데이터가 없습니다"}
        
        # 전체 성공률
        successful_records = sum(1 for r in self.performance_records if r.success)
        overall_success_rate = successful_records / total_records
        
        # 평균 품질 점수
        avg_quality = sum(r.quality_score for r in self.performance_records) / total_records
        
        # 카테고리별 통계
        category_stats = defaultdict(lambda: {"total": 0, "successful": 0, "avg_quality": 0})
        for record in self.performance_records:
            cat = record.query_category.value
            category_stats[cat]["total"] += 1
            if record.success:
                category_stats[cat]["successful"] += 1
            category_stats[cat]["avg_quality"] += record.quality_score
        
        # 카테고리별 평균 계산
        for cat, stats in category_stats.items():
            stats["success_rate"] = stats["successful"] / stats["total"]
            stats["avg_quality"] /= stats["total"]
        
        # 최고 성능 에이전트
        top_agents = []
        for agent_id, profile in self.agent_profiles.items():
            if profile.total_attempts >= 5:
                score = self._calculate_overall_score(profile, QueryCategory.GENERAL)
                top_agents.append((agent_id, score))
        
        top_agents.sort(key=lambda x: x[1], reverse=True)
        
        return {
            "total_records": total_records,
            "overall_success_rate": overall_success_rate,
            "avg_quality_score": avg_quality,
            "registered_agents": len(self.agent_profiles),
            "category_stats": dict(category_stats),
            "top_performing_agents": top_agents[:5],
            "learning_iterations": self.learning_iterations
        }
    
    def suggest_improvements(self) -> List[str]:
        """시스템 개선 제안"""
        suggestions = []
        
        # 성능이 낮은 카테고리 식별
        category_stats = defaultdict(lambda: {"total": 0, "successful": 0})
        for record in self.performance_records:
            cat = record.query_category.value
            category_stats[cat]["total"] += 1
            if record.success:
                category_stats[cat]["successful"] += 1
        
        for cat, stats in category_stats.items():
            if stats["total"] >= 10:  # 충분한 데이터가 있는 경우
                success_rate = stats["successful"] / stats["total"]
                if success_rate < 0.5:
                    suggestions.append(f"{cat} 카테고리의 성능이 낮습니다 (성공률: {success_rate:.1%}). 전문 에이전트 추가를 고려하세요.")
        
        # 응답 시간이 긴 에이전트 식별
        slow_agents = []
        for agent_id, profile in self.agent_profiles.items():
            if profile.avg_execution_time > 15.0:
                slow_agents.append((agent_id, profile.avg_execution_time))
        
        if slow_agents:
            suggestions.append(f"응답이 느린 에이전트들: {', '.join(f'{a}({t:.1f}s)' for a, t in slow_agents)}. 최적화가 필요합니다.")
        
        # 사용되지 않는 에이전트
        unused_agents = [agent_id for agent_id, profile in self.agent_profiles.items() 
                        if profile.total_attempts == 0]
        if unused_agents:
            suggestions.append(f"사용되지 않는 에이전트: {', '.join(unused_agents)}. 홍보나 개선이 필요합니다.")
        
        return suggestions
    
    def export_data(self) -> Dict[str, Any]:
        """데이터 내보내기 (백업/분석용)"""
        return {
            "performance_records": [asdict(record) for record in self.performance_records],
            "agent_profiles": {
                agent_id: {
                    **asdict(profile),
                    "recent_performance": list(profile.recent_performance)
                }
                for agent_id, profile in self.agent_profiles.items()
            },
            "category_agents": {
                category.value: agents for category, agents in self.category_agents.items()
            },
            "export_timestamp": time.time()
        }
    
    def import_data(self, data: Dict[str, Any]):
        """데이터 가져오기 (복원용)"""
        try:
            # 성능 기록 복원
            if "performance_records" in data:
                self.performance_records = [
                    PerformanceRecord(**record) for record in data["performance_records"]
                ]
            
            # 에이전트 프로필 복원
            if "agent_profiles" in data:
                for agent_id, profile_data in data["agent_profiles"].items():
                    # recent_performance를 deque로 변환
                    if "recent_performance" in profile_data:
                        profile_data["recent_performance"] = deque(
                            profile_data["recent_performance"], maxlen=100
                        )
                    self.agent_profiles[agent_id] = AgentPerformanceProfile(**profile_data)
            
            # 카테고리별 에이전트 복원
            if "category_agents" in data:
                for category_name, agents in data["category_agents"].items():
                    category = QueryCategory(category_name)
                    self.category_agents[category] = agents
            
            logger.info("✅ 성능 데이터 가져오기 완료")
            
        except Exception as e:
            logger.error(f"❌ 성능 데이터 가져오기 실패: {e}")
            raise


# 편의 함수들
def create_performance_tracker(config: Dict[str, Any] = None) -> AgentPerformanceTracker:
    """성능 추적기 생성 편의 함수"""
    return AgentPerformanceTracker(config)


if __name__ == "__main__":
    # 사용 예시
    def test_performance_tracker():
        # 성능 추적기 생성
        tracker = create_performance_tracker({
            "max_records": 1000,
            "learning_rate": 0.1
        })
        
        # 모의 성능 데이터 추가
        test_data = [
            ("calculator_agent", "123 + 456 계산해주세요", True, 0.9, 1.2),
            ("text_agent", "이 문서를 요약해주세요", True, 0.8, 3.5),
            ("calculator_agent", "파이썬 코드 작성해주세요", False, 0.3, 2.1),
            ("text_agent", "영어로 번역해주세요", True, 0.85, 2.8),
        ]
        
        for agent_id, query, success, quality, time in test_data:
            tracker.record_performance(agent_id, query, success, quality, time)
        
        # 예측 테스트
        predictions = tracker.predict_best_agents("100 + 200 계산해주세요")
        logger.info(f"계산 쿼리 예측 결과: {predictions}")

        # 인사이트 조회
        insights = tracker.get_system_insights()
        logger.info(f"시스템 인사이트: {insights}")

        # 개선 제안
        suggestions = tracker.suggest_improvements()
        logger.info(f"개선 제안: {suggestions}")
    
    # 테스트 실행
    test_performance_tracker()