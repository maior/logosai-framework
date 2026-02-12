"""
AgentCollaborationManager - 에이전트 간 협업 시스템

이 모듈은 에이전트가 자신의 전문 분야가 아닌 작업을 다른 전문 에이전트에게 위임할 수 있도록 하는
효율적인 협업 시스템을 제공합니다.

주요 기능:
- 에이전트 자동 발견 및 캐싱
- 컨텍스트 기반 최적 에이전트 선택
- 비동기 에이전트 호출 및 결과 통합
- 순환 호출 방지 시스템
- 결과 캐싱 및 성능 최적화
"""

from typing import Any, Dict, List, Optional, Union, Set, Tuple
from datetime import datetime, timedelta
import asyncio
import json
import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import importlib.util
import inspect
from loguru import logger
import traceback

# LogosAI imports
from .agent_types import AgentType, AgentResponse, AgentResponseType
from .agent import LogosAIAgent


class CollaborationReason(Enum):
    """협업 요청 이유"""
    INSUFFICIENT_CAPABILITY = "insufficient_capability"
    SPECIALIZED_TASK = "specialized_task"
    URL_DOCUMENT_PROCESSING = "url_document_processing"
    MATHEMATICAL_COMPUTATION = "mathematical_computation"
    CODE_GENERATION = "code_generation"
    IMAGE_PROCESSING = "image_processing"
    DATA_ANALYSIS = "data_analysis"


@dataclass
class CollaborationRequest:
    """에이전트 협업 요청"""
    source_agent: str
    target_capability: str
    request_data: Union[str, Dict[str, Any]]
    context: Dict[str, Any] = field(default_factory=dict)
    reason: CollaborationReason = CollaborationReason.INSUFFICIENT_CAPABILITY
    priority: str = "normal"  # low, normal, high, urgent
    timeout: int = 60  # seconds
    max_retries: int = 2
    
    def __post_init__(self):
        self.request_id = self._generate_request_id()
        self.created_at = datetime.now()
    
    def _generate_request_id(self) -> str:
        """요청 ID 생성"""
        content = f"{self.source_agent}:{self.target_capability}:{str(self.request_data)}"
        return hashlib.md5(content.encode()).hexdigest()[:12]


@dataclass
class CollaborationResult:
    """협업 결과"""
    request_id: str
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time: float = 0.0
    target_agent: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "request_id": self.request_id,
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "execution_time": self.execution_time,
            "target_agent": self.target_agent,
            "metadata": self.metadata
        }


class AgentCache:
    """에이전트 캐시 관리"""
    
    def __init__(self, max_size: int = 100, ttl_minutes: int = 30):
        self.cache: Dict[str, Any] = {}
        self.access_times: Dict[str, datetime] = {}
        self.max_size = max_size
        self.ttl = timedelta(minutes=ttl_minutes)
    
    def get(self, key: str) -> Optional[Any]:
        """캐시에서 에이전트 인스턴스 조회"""
        if key not in self.cache:
            return None
        
        # TTL 체크
        if datetime.now() - self.access_times[key] > self.ttl:
            self.remove(key)
            return None
        
        self.access_times[key] = datetime.now()
        return self.cache[key]
    
    def put(self, key: str, value: Any) -> None:
        """캐시에 에이전트 인스턴스 저장"""
        if len(self.cache) >= self.max_size:
            self._evict_oldest()
        
        self.cache[key] = value
        self.access_times[key] = datetime.now()
    
    def remove(self, key: str) -> None:
        """캐시에서 제거"""
        self.cache.pop(key, None)
        self.access_times.pop(key, None)
    
    def _evict_oldest(self) -> None:
        """가장 오래된 항목 제거"""
        if not self.access_times:
            return
        
        oldest_key = min(self.access_times, key=self.access_times.get)
        self.remove(oldest_key)
    
    def clear(self) -> None:
        """캐시 전체 삭제"""
        self.cache.clear()
        self.access_times.clear()


class CircularCallDetector:
    """순환 호출 감지 및 방지"""
    
    def __init__(self, max_depth: int = 5):
        self.call_stack: List[str] = []
        self.max_depth = max_depth
    
    def enter_call(self, agent_id: str, request_id: str) -> bool:
        """호출 시작 - 순환 호출 체크"""
        call_signature = f"{agent_id}:{request_id}"
        
        # 최대 깊이 체크
        if len(self.call_stack) >= self.max_depth:
            logger.warning(f"최대 호출 깊이 초과: {self.max_depth}")
            return False
        
        # 순환 호출 체크
        if call_signature in self.call_stack:
            logger.warning(f"순환 호출 감지: {call_signature}")
            return False
        
        self.call_stack.append(call_signature)
        return True
    
    def exit_call(self) -> None:
        """호출 종료"""
        if self.call_stack:
            self.call_stack.pop()
    
    def get_depth(self) -> int:
        """현재 호출 깊이"""
        return len(self.call_stack)


class AgentCollaborationManager:
    """에이전트 협업 관리자
    
    에이전트 간 효율적인 협업을 위한 핵심 관리자 클래스입니다.
    
    주요 기능:
    - 자동 에이전트 발견 및 라우팅
    - 비동기 에이전트 호출 및 결과 통합
    - 캐싱을 통한 성능 최적화
    - 순환 호출 방지
    - 상세한 로깅 및 메트릭
    """
    
    def __init__(self, 
                 agents_config_path: Optional[str] = None,
                 cache_size: int = 50,
                 cache_ttl_minutes: int = 30):
        """
        Args:
            agents_config_path: agents.json 파일 경로
            cache_size: 에이전트 캐시 크기
            cache_ttl_minutes: 캐시 TTL (분)
        """
        self.agents_config_path = agents_config_path
        self.agent_cache = AgentCache(max_size=cache_size, ttl_minutes=cache_ttl_minutes)
        self.circular_detector = CircularCallDetector()
        self.available_agents: Dict[str, Dict[str, Any]] = {}
        self.performance_metrics: Dict[str, List[float]] = {}
        
        # 에이전트 설정 로드
        self._load_agents_config()
        
        logger.info("🤝 AgentCollaborationManager 초기화 완료")
    
    def _load_agents_config(self) -> None:
        """agents.json에서 에이전트 설정 로드"""
        try:
            if not self.agents_config_path:
                # 기본 경로들 시도
                possible_paths = [
                    Path(__file__).parent / "examples" / "configs" / "agents.json",
                    Path(__file__).parent / "config" / "agents.json",
                    Path(__file__).parent / "examples" / "configs" / "agents.json"
                ]
                
                for path in possible_paths:
                    if path.exists():
                        self.agents_config_path = str(path)
                        break
            
            if not self.agents_config_path or not Path(self.agents_config_path).exists():
                logger.warning("agents.json 파일을 찾을 수 없습니다. 에이전트 설정을 수동으로 등록해야 합니다.")
                return
            
            with open(self.agents_config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # agents 배열에서 에이전트 정보 추출
            agents_list = config.get('agents', [])
            for agent_config in agents_list:
                agent_id = agent_config.get('agent_id')
                if agent_id:
                    self.available_agents[agent_id] = {
                        'name': agent_config.get('name', agent_id),
                        'description': agent_config.get('description', ''),
                        'capabilities': agent_config.get('capabilities', []),
                        'tags': agent_config.get('tags', []),
                        'metadata': agent_config.get('metadata', {}),
                        'examples': agent_config.get('examples', []),
                        'config': agent_config
                    }
            
            logger.info(f"✅ {len(self.available_agents)}개 에이전트 설정 로드 완료")
            
        except Exception as e:
            logger.error(f"에이전트 설정 로드 실패: {e}")
    
    def register_agent(self, agent_id: str, agent_info: Dict[str, Any]) -> None:
        """에이전트 수동 등록"""
        self.available_agents[agent_id] = agent_info
        logger.info(f"✅ 에이전트 등록: {agent_id}")
    
    async def find_best_agent_for_task(self, 
                                     task_description: str, 
                                     required_capabilities: List[str] = None,
                                     excluded_agents: Set[str] = None) -> Optional[str]:
        """작업에 가장 적합한 에이전트 찾기
        
        Args:
            task_description: 작업 설명
            required_capabilities: 필요한 기능 목록
            excluded_agents: 제외할 에이전트 목록
            
        Returns:
            가장 적합한 에이전트 ID 또는 None
        """
        if not self.available_agents:
            logger.warning("사용 가능한 에이전트가 없습니다")
            return None
        
        excluded_agents = excluded_agents or set()
        best_agent = None
        best_score = 0.0
        
        # 태스크 키워드 분석
        task_keywords = self._extract_keywords(task_description.lower())
        
        for agent_id, agent_info in self.available_agents.items():
            if agent_id in excluded_agents:
                continue
            
            score = self._calculate_agent_score(
                agent_info, task_keywords, required_capabilities
            )
            
            if score > best_score:
                best_score = score
                best_agent = agent_id
        
        if best_agent and best_score > 0.3:  # 최소 임계값
            logger.info(f"🎯 최적 에이전트 선택: {best_agent} (점수: {best_score:.2f})")
            return best_agent
        
        logger.warning(f"적합한 에이전트를 찾을 수 없습니다. 최고 점수: {best_score:.2f}")
        return None
    
    def _extract_keywords(self, text: str) -> List[str]:
        """텍스트에서 키워드 추출"""
        # URL 관련 키워드
        url_keywords = ["http", "https", "url", "웹", "사이트", "다운로드", "링크"]
        # 문서 관련 키워드
        doc_keywords = ["pdf", "docx", "문서", "파일", "분석", "요약", "내용"]
        # 수학 관련 키워드
        math_keywords = ["계산", "수학", "방정식", "미분", "적분", "통계"]
        # 코딩 관련 키워드
        code_keywords = ["코드", "프로그램", "함수", "구현", "개발", "스크립트"]
        
        found_keywords = []
        
        for keyword in url_keywords + doc_keywords + math_keywords + code_keywords:
            if keyword in text:
                found_keywords.append(keyword)
        
        return found_keywords
    
    def _calculate_agent_score(self, 
                             agent_info: Dict[str, Any], 
                             task_keywords: List[str],
                             required_capabilities: List[str] = None) -> float:
        """에이전트 적합성 점수 계산"""
        score = 0.0
        
        # 1. 키워드 매칭 (40%)
        agent_text = (
            agent_info.get('description', '') + ' ' +
            ' '.join(agent_info.get('tags', [])) + ' ' +
            ' '.join([cap.get('description', '') for cap in agent_info.get('capabilities', [])])
        ).lower()
        
        keyword_matches = sum(1 for keyword in task_keywords if keyword in agent_text)
        keyword_score = min(keyword_matches / max(len(task_keywords), 1), 1.0) * 0.4
        score += keyword_score
        
        # 2. 필수 기능 매칭 (30%)
        if required_capabilities:
            capability_ids = [cap.get('id', '') for cap in agent_info.get('capabilities', [])]
            capability_matches = sum(1 for req_cap in required_capabilities 
                                   if any(req_cap in cap_id for cap_id in capability_ids))
            capability_score = min(capability_matches / len(required_capabilities), 1.0) * 0.3
            score += capability_score
        
        # 3. 에이전트 타입 매칭 (20%)
        agent_type = agent_info.get('metadata', {}).get('agent_type', '')
        type_bonus = 0.0
        
        # 특정 타입에 대한 보너스
        if any(keyword in task_keywords for keyword in ["pdf", "url", "문서", "다운로드"]):
            if "URL_DOCUMENT" in agent_type or "DOCUMENT" in agent_type:
                type_bonus = 0.2
        elif any(keyword in task_keywords for keyword in ["수학", "계산", "방정식"]):
            if "MATH" in agent_type or "CALCULATION" in agent_type:
                type_bonus = 0.2
        elif any(keyword in task_keywords for keyword in ["코드", "프로그램", "구현"]):
            if "CODE" in agent_type or "PROGRAMMING" in agent_type:
                type_bonus = 0.2
        
        score += type_bonus
        
        # 4. 성능 히스토리 (10%)
        agent_id = agent_info.get('config', {}).get('agent_id', '')
        if agent_id in self.performance_metrics:
            avg_performance = sum(self.performance_metrics[agent_id]) / len(self.performance_metrics[agent_id])
            score += avg_performance * 0.1
        
        return min(score, 1.0)
    
    async def _load_agent_instance(self, agent_id: str) -> Optional[LogosAIAgent]:
        """에이전트 인스턴스 로드"""
        # 캐시에서 먼저 확인
        cached_agent = self.agent_cache.get(agent_id)
        if cached_agent:
            logger.debug(f"💾 캐시에서 에이전트 로드: {agent_id}")
            return cached_agent
        
        try:
            agent_config = self.available_agents.get(agent_id, {}).get('config', {})
            metadata = agent_config.get('metadata', {})
            
            module_name = metadata.get('module_name', agent_id)
            class_name = metadata.get('class_name', 'Agent')
            
            # 에이전트 모듈 동적 로드
            agents_dir = Path(__file__).parent / "examples" / "agents"
            module_path = agents_dir / f"{module_name}.py"
            
            if not module_path.exists():
                logger.error(f"에이전트 모듈을 찾을 수 없습니다: {module_path}")
                return None
            
            # 모듈 동적 import
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # 클래스 인스턴스 생성
            agent_class = getattr(module, class_name)
            agent_instance = agent_class(config=agent_config)
            
            # 캐시에 저장
            self.agent_cache.put(agent_id, agent_instance)
            
            logger.info(f"🔄 에이전트 인스턴스 로드: {agent_id}")
            return agent_instance
            
        except Exception as e:
            logger.error(f"에이전트 로드 실패 {agent_id}: {e}")
            logger.debug(f"상세 오류: {traceback.format_exc()}")
            return None
    
    async def collaborate(self, request: CollaborationRequest) -> CollaborationResult:
        """에이전트 협업 실행
        
        Args:
            request: 협업 요청
            
        Returns:
            협업 결과
        """
        start_time = time.time()
        
        # 순환 호출 체크
        if not self.circular_detector.enter_call(request.source_agent, request.request_id):
            return CollaborationResult(
                request_id=request.request_id,
                success=False,
                error="순환 호출이 감지되었습니다",
                execution_time=time.time() - start_time
            )
        
        try:
            logger.info(f"🤝 협업 시작: {request.source_agent} -> {request.target_capability}")
            
            # 1. 최적 에이전트 찾기
            task_description = f"{request.target_capability} {str(request.request_data)}"
            target_agent_id = await self.find_best_agent_for_task(
                task_description=task_description,
                excluded_agents={request.source_agent}
            )
            
            if not target_agent_id:
                return CollaborationResult(
                    request_id=request.request_id,
                    success=False,
                    error="적합한 에이전트를 찾을 수 없습니다",
                    execution_time=time.time() - start_time
                )
            
            # 2. 에이전트 인스턴스 로드
            agent_instance = await self._load_agent_instance(target_agent_id)
            if not agent_instance:
                return CollaborationResult(
                    request_id=request.request_id,
                    success=False,
                    error=f"에이전트 {target_agent_id} 로드 실패",
                    execution_time=time.time() - start_time,
                    target_agent=target_agent_id
                )
            
            # 3. 에이전트 호출
            try:
                # 타임아웃 설정
                result = await asyncio.wait_for(
                    agent_instance.process(request.request_data),
                    timeout=request.timeout
                )
                
                execution_time = time.time() - start_time
                
                # 성능 메트릭 업데이트
                self._update_performance_metrics(target_agent_id, execution_time, True)
                
                logger.info(f"✅ 협업 성공: {request.source_agent} -> {target_agent_id} ({execution_time:.2f}s)")
                
                return CollaborationResult(
                    request_id=request.request_id,
                    success=True,
                    result=result,
                    execution_time=execution_time,
                    target_agent=target_agent_id,
                    metadata={
                        "collaboration_reason": request.reason.value,
                        "call_depth": self.circular_detector.get_depth()
                    }
                )
                
            except asyncio.TimeoutError:
                execution_time = time.time() - start_time
                self._update_performance_metrics(target_agent_id, execution_time, False)
                
                return CollaborationResult(
                    request_id=request.request_id,
                    success=False,
                    error=f"에이전트 응답 시간 초과 ({request.timeout}초)",
                    execution_time=execution_time,
                    target_agent=target_agent_id
                )
            
            except Exception as e:
                execution_time = time.time() - start_time
                self._update_performance_metrics(target_agent_id, execution_time, False)
                
                return CollaborationResult(
                    request_id=request.request_id,
                    success=False,
                    error=f"에이전트 처리 오류: {str(e)}",
                    execution_time=execution_time,
                    target_agent=target_agent_id
                )
        
        finally:
            self.circular_detector.exit_call()
    
    def _update_performance_metrics(self, agent_id: str, execution_time: float, success: bool) -> None:
        """성능 메트릭 업데이트"""
        if agent_id not in self.performance_metrics:
            self.performance_metrics[agent_id] = []
        
        # 성공률을 시간과 함께 고려한 점수
        score = (1.0 if success else 0.0) * max(0.1, 1.0 / (1.0 + execution_time))
        
        self.performance_metrics[agent_id].append(score)
        
        # 최근 20개 기록만 유지
        if len(self.performance_metrics[agent_id]) > 20:
            self.performance_metrics[agent_id] = self.performance_metrics[agent_id][-20:]
    
    async def get_collaboration_suggestions(self, 
                                         source_agent: str, 
                                         task_description: str) -> List[Dict[str, Any]]:
        """협업 제안 목록 반환"""
        suggestions = []
        
        # URL 감지
        if any(keyword in task_description.lower() 
               for keyword in ["http", "https", "url", ".pdf", ".docx"]):
            agent_id = await self.find_best_agent_for_task(
                "URL 문서 다운로드 및 분석",
                required_capabilities=["url_document_download"],
                excluded_agents={source_agent}
            )
            if agent_id:
                suggestions.append({
                    "agent_id": agent_id,
                    "reason": CollaborationReason.URL_DOCUMENT_PROCESSING.value,
                    "confidence": 0.9,
                    "description": "URL에서 문서를 다운로드하고 분석"
                })
        
        # 수학 계산 감지
        if any(keyword in task_description.lower() 
               for keyword in ["계산", "수학", "방정식", "미분", "적분"]):
            agent_id = await self.find_best_agent_for_task(
                "수학 계산 및 분석",
                excluded_agents={source_agent}
            )
            if agent_id:
                suggestions.append({
                    "agent_id": agent_id,
                    "reason": CollaborationReason.MATHEMATICAL_COMPUTATION.value,
                    "confidence": 0.8,
                    "description": "수학적 계산 및 분석 수행"
                })
        
        return suggestions
    
    def get_metrics(self) -> Dict[str, Any]:
        """성능 메트릭 조회"""
        return {
            "available_agents": len(self.available_agents),
            "cached_agents": len(self.agent_cache.cache),
            "performance_metrics": {
                agent_id: {
                    "average_score": sum(scores) / len(scores),
                    "call_count": len(scores),
                    "recent_score": scores[-1] if scores else 0
                }
                for agent_id, scores in self.performance_metrics.items()
            }
        }
    
    def clear_cache(self) -> None:
        """캐시 초기화"""
        self.agent_cache.clear()
        logger.info("🗑️  에이전트 캐시 초기화 완료")


# 전역 협업 매니저 인스턴스 (싱글톤 패턴)
_collaboration_manager: Optional[AgentCollaborationManager] = None


def get_collaboration_manager(force_reload: bool = False) -> AgentCollaborationManager:
    """전역 협업 매니저 인스턴스 반환"""
    global _collaboration_manager
    
    if _collaboration_manager is None or force_reload:
        _collaboration_manager = AgentCollaborationManager()
    
    return _collaboration_manager


# 편의 함수들
async def collaborate_with_agent(source_agent: str,
                               target_capability: str, 
                               request_data: Union[str, Dict[str, Any]],
                               context: Dict[str, Any] = None,
                               reason: CollaborationReason = CollaborationReason.SPECIALIZED_TASK) -> CollaborationResult:
    """에이전트 협업 편의 함수"""
    manager = get_collaboration_manager()
    
    request = CollaborationRequest(
        source_agent=source_agent,
        target_capability=target_capability,
        request_data=request_data,
        context=context or {},
        reason=reason
    )
    
    return await manager.collaborate(request)


async def find_agent_for_url_processing(source_agent: str, url: str) -> Optional[str]:
    """URL 처리를 위한 최적 에이전트 찾기"""
    manager = get_collaboration_manager()
    
    return await manager.find_best_agent_for_task(
        task_description=f"URL 문서 처리: {url}",
        required_capabilities=["url_document_download", "multi_format_text_extraction"],
        excluded_agents={source_agent}
    )


async def find_agent_for_math_computation(source_agent: str, problem: str) -> Optional[str]:
    """수학 계산을 위한 최적 에이전트 찾기"""
    manager = get_collaboration_manager()
    
    return await manager.find_best_agent_for_task(
        task_description=f"수학 계산: {problem}",
        excluded_agents={source_agent}
    )