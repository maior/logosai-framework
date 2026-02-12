"""
LogosAI 동적 에이전트 능력 관리 시스템

에이전트가 자신의 실제 능력을 동적으로 파악하고 업데이트하는 시스템
"""

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
from loguru import logger
from pathlib import Path
import statistics


@dataclass
class PerformanceMetric:
    """성능 메트릭"""
    task_type: str
    success_rate: float
    average_response_time: float
    quality_score: float
    user_satisfaction: float
    sample_size: int
    last_updated: datetime


@dataclass
class CapabilityProfile:
    """에이전트 능력 프로필"""
    agent_id: str
    capabilities: Dict[str, PerformanceMetric]
    overall_performance: float
    confidence_level: float
    last_assessment: datetime
    assessment_count: int


class DynamicCapabilityManager:
    """동적 에이전트 능력 관리자"""
    
    def __init__(self, agent_id: str, data_dir: str = "agent_profiles"):
        self.agent_id = agent_id
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        
        self.profile_file = self.data_dir / f"{agent_id}_capability_profile.json"
        self.performance_history = []
        self.capability_profile = self._load_or_create_profile()
        
        # 벤치마크 테스트 정의
        self.benchmark_tests = {
            "code_generation": [
                "Python으로 간단한 계산기 함수를 만들어줘",
                "파일을 읽고 쓰는 함수를 구현해줘",
                "간단한 REST API 엔드포인트를 작성해줘"
            ],
            "text_analysis": [
                "다음 텍스트의 주요 키워드를 추출해줘: '인공지능은 미래 기술의 핵심입니다'",
                "이 문장의 감정을 분석해줘: '오늘 정말 기분이 좋다'",
                "텍스트를 3줄로 요약해줘"
            ],
            "information_search": [
                "Python의 리스트와 튜플의 차이점을 설명해줘",
                "기계학습의 기본 개념을 설명해줘",
                "웹 개발에서 프론트엔드와 백엔드의 역할을 설명해줘"
            ],
            "problem_solving": [
                "1부터 100까지의 합을 구하는 알고리즘을 설명해줘",
                "두 수의 최대공약수를 구하는 방법을 설명해줘",
                "간단한 정렬 알고리즘을 설명해줘"
            ],
            "communication": [
                "이메일 템플릿을 작성해줘",
                "회의 안건을 정리해줘",
                "프로젝트 진행 상황을 보고서 형태로 작성해줘"
            ]
        }
    
    def _load_or_create_profile(self) -> CapabilityProfile:
        """프로필 로드 또는 생성"""
        if self.profile_file.exists():
            try:
                with open(self.profile_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                # PerformanceMetric 객체들 복원
                capabilities = {}
                for task_type, metric_data in data.get('capabilities', {}).items():
                    metric_data['last_updated'] = datetime.fromisoformat(metric_data['last_updated'])
                    capabilities[task_type] = PerformanceMetric(**metric_data)
                
                return CapabilityProfile(
                    agent_id=data['agent_id'],
                    capabilities=capabilities,
                    overall_performance=data.get('overall_performance', 0.0),
                    confidence_level=data.get('confidence_level', 0.0),
                    last_assessment=datetime.fromisoformat(data['last_assessment']),
                    assessment_count=data.get('assessment_count', 0)
                )
            except Exception as e:
                logger.warning(f"프로필 로드 실패, 새로 생성: {e}")
        
        # 새 프로필 생성
        return CapabilityProfile(
            agent_id=self.agent_id,
            capabilities={},
            overall_performance=0.0,
            confidence_level=0.0,
            last_assessment=datetime.now(),
            assessment_count=0
        )
    
    def _save_profile(self):
        """프로필 저장"""
        try:
            # datetime 객체를 문자열로 변환
            profile_dict = asdict(self.capability_profile)
            profile_dict['last_assessment'] = self.capability_profile.last_assessment.isoformat()
            
            # PerformanceMetric의 datetime도 변환
            for task_type, metric in profile_dict['capabilities'].items():
                metric['last_updated'] = metric['last_updated'].isoformat()
            
            with open(self.profile_file, 'w', encoding='utf-8') as f:
                json.dump(profile_dict, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"프로필 저장 실패: {e}")
    
    async def run_self_assessment(self, agent_instance) -> Dict[str, Any]:
        """종합 자가 진단 실행"""
        logger.info(f"에이전트 {self.agent_id} 자가 진단 시작")
        
        assessment_results = {}
        
        for task_type, test_queries in self.benchmark_tests.items():
            logger.info(f"  {task_type} 능력 테스트 중...")
            
            task_results = []
            
            for query in test_queries:
                try:
                    start_time = time.time()
                    
                    # 에이전트에 테스트 쿼리 실행
                    if hasattr(agent_instance, 'process_query'):
                        result = await agent_instance.process_query(query)
                    else:
                        # 다른 인터페이스가 있다면 적절히 조정
                        result = await agent_instance.query(query)
                    
                    execution_time = time.time() - start_time
                    
                    # 결과 품질 평가
                    quality_score = await self._evaluate_response_quality(query, result)
                    
                    task_results.append({
                        "query": query,
                        "success": True,
                        "execution_time": execution_time,
                        "quality_score": quality_score,
                        "result_length": len(str(result)) if result else 0
                    })
                    
                except Exception as e:
                    logger.warning(f"테스트 쿼리 실패: {query[:50]}... - {str(e)}")
                    task_results.append({
                        "query": query,
                        "success": False,
                        "execution_time": 0,
                        "quality_score": 0.0,
                        "error": str(e)
                    })
            
            # 태스크별 성능 메트릭 계산
            success_results = [r for r in task_results if r["success"]]
            
            if success_results:
                success_rate = len(success_results) / len(task_results)
                avg_response_time = statistics.mean([r["execution_time"] for r in success_results])
                avg_quality = statistics.mean([r["quality_score"] for r in success_results])
            else:
                success_rate = 0.0
                avg_response_time = 0.0
                avg_quality = 0.0
            
            # 성능 메트릭 업데이트
            metric = PerformanceMetric(
                task_type=task_type,
                success_rate=success_rate,
                average_response_time=avg_response_time,
                quality_score=avg_quality,
                user_satisfaction=0.7,  # 기본값, 실제 사용시 피드백으로 업데이트
                sample_size=len(task_results),
                last_updated=datetime.now()
            )
            
            self.capability_profile.capabilities[task_type] = metric
            assessment_results[task_type] = {
                "success_rate": success_rate,
                "average_response_time": avg_response_time,
                "quality_score": avg_quality,
                "sample_size": len(task_results),
                "detailed_results": task_results
            }
        
        # 전체 성능 점수 계산
        await self._calculate_overall_performance()
        
        # 프로필 업데이트 및 저장
        self.capability_profile.last_assessment = datetime.now()
        self.capability_profile.assessment_count += 1
        self._save_profile()
        
        logger.info(f"자가 진단 완료: 전체 성능 {self.capability_profile.overall_performance:.2f}")
        
        return {
            "agent_id": self.agent_id,
            "assessment_timestamp": datetime.now().isoformat(),
            "overall_performance": self.capability_profile.overall_performance,
            "confidence_level": self.capability_profile.confidence_level,
            "task_performances": assessment_results,
            "recommendations": await self._generate_improvement_recommendations()
        }
    
    async def _evaluate_response_quality(self, query: str, response: Any) -> float:
        """응답 품질 평가"""
        if not response:
            return 0.0
        
        response_str = str(response)
        
        # 기본 품질 체크
        quality_score = 0.0
        
        # 1. 응답 길이 체크 (너무 짧거나 길지 않은지)
        if 10 <= len(response_str) <= 5000:
            quality_score += 0.3
        
        # 2. 에러 메시지가 없는지 체크
        error_indicators = ["error", "failed", "exception", "오류", "실패", "에러"]
        if not any(indicator in response_str.lower() for indicator in error_indicators):
            quality_score += 0.3
        
        # 3. 구체적인 내용이 있는지 체크
        if len(response_str.split()) >= 5:  # 최소 5단어 이상
            quality_score += 0.2
        
        # 4. 쿼리 타입별 특별 체크
        if "코드" in query or "함수" in query or "구현" in query:
            # 코드 관련 쿼리의 경우
            if any(keyword in response_str for keyword in ["def ", "function", "class ", "import", "return"]):
                quality_score += 0.2
        
        elif "설명" in query or "차이점" in query:
            # 설명 관련 쿼리의 경우
            if len(response_str.split('.')) >= 2:  # 최소 2문장 이상
                quality_score += 0.2
        
        return min(quality_score, 1.0)
    
    async def _calculate_overall_performance(self):
        """전체 성능 점수 계산"""
        if not self.capability_profile.capabilities:
            self.capability_profile.overall_performance = 0.0
            self.capability_profile.confidence_level = 0.0
            return
        
        # 가중 평균 계산
        total_score = 0.0
        total_weight = 0.0
        
        for task_type, metric in self.capability_profile.capabilities.items():
            # 성공률, 품질, 속도를 종합한 점수
            task_score = (
                metric.success_rate * 0.4 +
                metric.quality_score * 0.4 +
                (1.0 / (1.0 + metric.average_response_time)) * 0.2
            )
            
            # 샘플 크기에 따른 가중치
            weight = min(metric.sample_size / 10.0, 1.0)
            
            total_score += task_score * weight
            total_weight += weight
        
        self.capability_profile.overall_performance = total_score / total_weight if total_weight > 0 else 0.0
        
        # 신뢰도 계산 (평가 횟수와 샘플 크기 고려)
        total_samples = sum(metric.sample_size for metric in self.capability_profile.capabilities.values())
        confidence = min(total_samples / 50.0, 1.0)  # 50개 샘플에서 100% 신뢰도
        confidence *= min(self.capability_profile.assessment_count / 5.0, 1.0)  # 5회 평가에서 100%
        
        self.capability_profile.confidence_level = confidence
    
    async def _generate_improvement_recommendations(self) -> List[str]:
        """개선 권장사항 생성"""
        recommendations = []
        
        for task_type, metric in self.capability_profile.capabilities.items():
            if metric.success_rate < 0.7:
                recommendations.append(f"{task_type} 영역의 성공률이 낮습니다 ({metric.success_rate:.1%}). 추가 학습이 필요합니다.")
            
            if metric.quality_score < 0.6:
                recommendations.append(f"{task_type} 영역의 응답 품질이 낮습니다 ({metric.quality_score:.1%}). 응답 개선이 필요합니다.")
            
            if metric.average_response_time > 5.0:
                recommendations.append(f"{task_type} 영역의 응답 시간이 깁니다 ({metric.average_response_time:.1f}초). 성능 최적화가 필요합니다.")
        
        if self.capability_profile.overall_performance < 0.5:
            recommendations.append("전반적인 성능이 낮습니다. 종합적인 개선이 필요합니다.")
        
        return recommendations
    
    async def update_capability_from_usage(self, task_type: str, success: bool, 
                                         execution_time: float, user_satisfaction: float = None):
        """실사용 기반 능력 업데이트"""
        
        # 실시간 성능 히스토리에 추가
        self.performance_history.append({
            "timestamp": datetime.now(),
            "task_type": task_type,
            "success": success,
            "execution_time": execution_time,
            "user_satisfaction": user_satisfaction
        })
        
        # 최근 100개 기록만 유지
        if len(self.performance_history) > 100:
            self.performance_history = self.performance_history[-100:]
        
        # 태스크 타입별 성능 재계산
        task_records = [r for r in self.performance_history if r["task_type"] == task_type]
        
        if len(task_records) >= 5:  # 최소 5개 기록이 있을 때만 업데이트
            success_rate = len([r for r in task_records if r["success"]]) / len(task_records)
            avg_time = statistics.mean([r["execution_time"] for r in task_records])
            
            # 사용자 만족도가 있는 경우만 계산
            satisfaction_scores = [r["user_satisfaction"] for r in task_records if r["user_satisfaction"] is not None]
            avg_satisfaction = statistics.mean(satisfaction_scores) if satisfaction_scores else 0.7
            
            # 기존 메트릭 업데이트 또는 새로 생성
            if task_type in self.capability_profile.capabilities:
                existing_metric = self.capability_profile.capabilities[task_type]
                # 기존 데이터와 새 데이터를 가중 평균
                weight_old = 0.7
                weight_new = 0.3
                
                updated_metric = PerformanceMetric(
                    task_type=task_type,
                    success_rate=existing_metric.success_rate * weight_old + success_rate * weight_new,
                    average_response_time=existing_metric.average_response_time * weight_old + avg_time * weight_new,
                    quality_score=existing_metric.quality_score * weight_old + 0.7 * weight_new,  # 임시값
                    user_satisfaction=existing_metric.user_satisfaction * weight_old + avg_satisfaction * weight_new,
                    sample_size=existing_metric.sample_size + len(task_records),
                    last_updated=datetime.now()
                )
            else:
                updated_metric = PerformanceMetric(
                    task_type=task_type,
                    success_rate=success_rate,
                    average_response_time=avg_time,
                    quality_score=0.7,  # 임시 기본값
                    user_satisfaction=avg_satisfaction,
                    sample_size=len(task_records),
                    last_updated=datetime.now()
                )
            
            self.capability_profile.capabilities[task_type] = updated_metric
            
            # 전체 성능 재계산
            await self._calculate_overall_performance()
            
            # 프로필 저장
            self._save_profile()
            
            logger.info(f"능력 업데이트: {task_type} - 성공률: {success_rate:.2f}, 응답시간: {avg_time:.2f}s")
    
    def get_capability_summary(self) -> Dict[str, Any]:
        """능력 요약 반환"""
        return {
            "agent_id": self.agent_id,
            "overall_performance": self.capability_profile.overall_performance,
            "confidence_level": self.capability_profile.confidence_level,
            "last_assessment": self.capability_profile.last_assessment.isoformat(),
            "assessment_count": self.capability_profile.assessment_count,
            "capabilities": {
                task_type: {
                    "success_rate": metric.success_rate,
                    "average_response_time": metric.average_response_time,
                    "quality_score": metric.quality_score,
                    "user_satisfaction": metric.user_satisfaction,
                    "sample_size": metric.sample_size
                }
                for task_type, metric in self.capability_profile.capabilities.items()
            }
        }
    
    def should_run_assessment(self) -> bool:
        """재평가가 필요한지 판단"""
        
        # 처음 평가하는 경우
        if self.capability_profile.assessment_count == 0:
            return True
        
        # 마지막 평가로부터 일정 시간이 지난 경우
        time_since_last = datetime.now() - self.capability_profile.last_assessment
        if time_since_last > timedelta(days=7):  # 일주일마다
            return True
        
        # 신뢰도가 낮은 경우
        if self.capability_profile.confidence_level < 0.5:
            return True
        
        # 성능이 급격히 변한 경우 (실사용 데이터 기반)
        if len(self.performance_history) >= 20:
            recent_success_rate = len([r for r in self.performance_history[-20:] if r["success"]]) / 20
            if abs(recent_success_rate - self.capability_profile.overall_performance) > 0.2:
                return True
        
        return False


# 편의 함수들
async def create_agent_capability_manager(agent_id: str) -> DynamicCapabilityManager:
    """에이전트 능력 관리자 생성"""
    return DynamicCapabilityManager(agent_id)


async def run_agent_self_assessment(agent_id: str, agent_instance) -> Dict[str, Any]:
    """에이전트 자가 진단 실행"""
    manager = DynamicCapabilityManager(agent_id)
    return await manager.run_self_assessment(agent_instance)


async def get_agent_capabilities(agent_id: str) -> Dict[str, Any]:
    """에이전트 능력 정보 조회"""
    manager = DynamicCapabilityManager(agent_id)
    return manager.get_capability_summary()