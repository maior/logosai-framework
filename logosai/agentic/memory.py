"""
AgenticMemory - 메모리 시스템

장단기 메모리 관리를 통해 에이전트의 학습과 컨텍스트 유지를 지원합니다.
"""

import asyncio
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime, timedelta
from loguru import logger
import json
import hashlib
from collections import deque, defaultdict


class MemoryType(Enum):
    """메모리 타입"""
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class MemoryImportance(Enum):
    """메모리 중요도"""
    CRITICAL = 5
    HIGH = 4
    MEDIUM = 3
    LOW = 2
    TRIVIAL = 1


@dataclass
class Memory:
    """메모리 단위"""
    id: str
    type: MemoryType
    content: Any
    context: Dict[str, Any] = field(default_factory=dict)
    importance: MemoryImportance = MemoryImportance.MEDIUM
    created_at: datetime = field(default_factory=datetime.now)
    accessed_at: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    decay_rate: float = 0.1  # 망각 속도
    associations: List[str] = field(default_factory=list)  # 연관된 메모리 ID들
    
    def __post_init__(self):
        if not self.id:
            # ID 자동 생성
            content_str = str(self.content)[:100]
            self.id = hashlib.md5(f"{content_str}{self.created_at}".encode()).hexdigest()[:12]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "content": self.content,
            "context": self.context,
            "importance": self.importance.value,
            "created_at": self.created_at.isoformat(),
            "accessed_at": self.accessed_at.isoformat(),
            "access_count": self.access_count,
            "decay_rate": self.decay_rate,
            "associations": self.associations
        }
    
    def access(self):
        """메모리 접근 시 호출"""
        self.accessed_at = datetime.now()
        self.access_count += 1
    
    def get_strength(self) -> float:
        """메모리 강도 계산 (0-1)"""
        # 시간 경과에 따른 감쇠
        time_elapsed = (datetime.now() - self.accessed_at).total_seconds() / 3600  # hours
        time_decay = max(0, 1 - (time_elapsed * self.decay_rate))
        
        # 접근 빈도에 따른 강화
        access_strength = min(1, self.access_count / 10)
        
        # 중요도 가중치
        importance_weight = self.importance.value / 5
        
        # 종합 강도
        strength = (time_decay * 0.4 + access_strength * 0.3 + importance_weight * 0.3)
        return min(1, max(0, strength))


@dataclass
class ShortTermMemory:
    """단기 메모리"""
    capacity: int = 7  # Miller's Magic Number
    memories: deque = field(default_factory=deque)
    
    def add(self, memory: Memory) -> bool:
        """메모리 추가"""
        if len(self.memories) >= self.capacity:
            # 가장 오래된 메모리 제거
            self.memories.popleft()
        
        self.memories.append(memory)
        return True
    
    def get_all(self) -> List[Memory]:
        """모든 단기 메모리 반환"""
        return list(self.memories)
    
    def clear(self):
        """단기 메모리 초기화"""
        self.memories.clear()
    
    def find(self, query: str) -> List[Memory]:
        """단기 메모리 검색"""
        results = []
        query_lower = query.lower()
        
        for memory in self.memories:
            content_str = str(memory.content).lower()
            if query_lower in content_str:
                results.append(memory)
        
        return results


@dataclass
class LongTermMemory:
    """장기 메모리"""
    max_size: int = 1000
    memories: Dict[str, Memory] = field(default_factory=dict)
    index: Dict[str, List[str]] = field(default_factory=lambda: defaultdict(list))  # 키워드 인덱스
    
    def add(self, memory: Memory) -> bool:
        """메모리 추가"""
        if len(self.memories) >= self.max_size:
            # 가장 약한 메모리 제거
            self._evict_weakest()
        
        self.memories[memory.id] = memory
        self._update_index(memory)
        return True
    
    def get(self, memory_id: str) -> Optional[Memory]:
        """메모리 조회"""
        memory = self.memories.get(memory_id)
        if memory:
            memory.access()
        return memory
    
    def _update_index(self, memory: Memory):
        """인덱스 업데이트"""
        # 간단한 키워드 추출
        content_str = str(memory.content)
        keywords = content_str.lower().split()[:10]  # 상위 10개 단어
        
        for keyword in keywords:
            if len(keyword) > 3:  # 3글자 이상만
                self.index[keyword].append(memory.id)
    
    def _evict_weakest(self):
        """가장 약한 메모리 제거"""
        if not self.memories:
            return
        
        weakest_id = None
        weakest_strength = 1.0
        
        for memory_id, memory in self.memories.items():
            strength = memory.get_strength()
            if strength < weakest_strength:
                weakest_strength = strength
                weakest_id = memory_id
        
        if weakest_id:
            del self.memories[weakest_id]
            # 인덱스에서도 제거
            for keyword_list in self.index.values():
                if weakest_id in keyword_list:
                    keyword_list.remove(weakest_id)
    
    def find(self, query: str, limit: int = 10) -> List[Memory]:
        """장기 메모리 검색"""
        query_lower = query.lower()
        keywords = query_lower.split()
        
        # 키워드로 후보 메모리 찾기
        candidate_ids = set()
        for keyword in keywords:
            if keyword in self.index:
                candidate_ids.update(self.index[keyword])
        
        # 후보 메모리들을 강도순으로 정렬
        results = []
        for memory_id in candidate_ids:
            if memory_id in self.memories:
                memory = self.memories[memory_id]
                results.append((memory.get_strength(), memory))
        
        # 강도 높은 순으로 정렬
        results.sort(key=lambda x: x[0], reverse=True)
        
        return [memory for _, memory in results[:limit]]
    
    def consolidate(self):
        """메모리 통합 (유사한 메모리 병합)"""
        # 간단한 구현: 중요도가 낮고 오래된 메모리 정리
        to_remove = []
        
        for memory_id, memory in self.memories.items():
            if (memory.importance == MemoryImportance.TRIVIAL and 
                memory.get_strength() < 0.3):
                to_remove.append(memory_id)
        
        for memory_id in to_remove:
            del self.memories[memory_id]
        
        logger.info(f"Consolidated memory: removed {len(to_remove)} weak memories")


class AgenticMemory:
    """
    에이전트 메모리 시스템
    
    단기 및 장기 메모리를 관리하고, 효율적인 정보 저장과 검색을 지원합니다.
    """
    
    def __init__(self, short_term_capacity: int = 7, long_term_size: int = 1000):
        """
        AgenticMemory 초기화
        
        Args:
            short_term_capacity: 단기 메모리 용량
            long_term_size: 장기 메모리 최대 크기
        """
        self.short_term = ShortTermMemory(capacity=short_term_capacity)
        self.long_term = LongTermMemory(max_size=long_term_size)
        
        # 메모리 타입별 저장소
        self.episodic_memories: List[Memory] = []  # 에피소드 메모리
        self.semantic_memories: Dict[str, Any] = {}  # 의미 메모리 (사실, 개념)
        self.procedural_memories: Dict[str, Any] = {}  # 절차 메모리 (스킬, 방법)
        
        logger.info(f"AgenticMemory initialized (STM: {short_term_capacity}, LTM: {long_term_size})")
    
    # 하위 호환성을 위한 속성들
    @property
    def short_term_memory(self):
        """하위 호환성을 위한 short_term_memory 속성"""
        return self.short_term.memories
    
    @property 
    def long_term_memory(self):
        """하위 호환성을 위한 long_term_memory 속성"""
        return list(self.long_term.memories.values())
    
    def store_short_term(self, content: Any, context: Dict[str, Any] = None,
                        importance: MemoryImportance = MemoryImportance.MEDIUM) -> Memory:
        """단기 메모리에 저장"""
        memory = Memory(
            id="",  # 자동 생성됨
            type=MemoryType.SHORT_TERM,
            content=content,
            context=context or {},
            importance=importance
        )
        
        self.short_term.add(memory)
        logger.debug(f"Stored in short-term memory: {memory.id}")
        
        return memory
    
    def store_long_term(self, content: Any, context: Dict[str, Any] = None,
                       importance: MemoryImportance = MemoryImportance.MEDIUM) -> Memory:
        """장기 메모리에 저장"""
        memory = Memory(
            id="",  # 자동 생성됨
            type=MemoryType.LONG_TERM,
            content=content,
            context=context or {},
            importance=importance
        )
        
        self.long_term.add(memory)
        logger.debug(f"Stored in long-term memory: {memory.id}")
        
        return memory
    
    def store_episode(self, episode: Dict[str, Any]) -> Memory:
        """에피소드 메모리 저장"""
        memory = Memory(
            id="",
            type=MemoryType.EPISODIC,
            content=episode,
            importance=MemoryImportance.MEDIUM
        )
        
        self.episodic_memories.append(memory)
        
        # 중요한 에피소드는 장기 메모리에도 저장
        if memory.importance.value >= MemoryImportance.HIGH.value:
            self.long_term.add(memory)
        
        logger.debug(f"Stored episodic memory: {memory.id}")
        return memory
    
    def store_fact(self, key: str, value: Any) -> None:
        """의미 메모리 (사실) 저장"""
        self.semantic_memories[key] = {
            "value": value,
            "stored_at": datetime.now(),
            "type": MemoryType.SEMANTIC.value
        }
        logger.debug(f"Stored semantic memory: {key}")
    
    def store_procedure(self, name: str, steps: List[str]) -> None:
        """절차 메모리 저장"""
        self.procedural_memories[name] = {
            "steps": steps,
            "stored_at": datetime.now(),
            "type": MemoryType.PROCEDURAL.value
        }
        logger.debug(f"Stored procedural memory: {name}")
    
    def add(self, content: Any, context: Dict[str, Any] = None,
            importance: MemoryImportance = MemoryImportance.MEDIUM,
            memory_type: str = "episode") -> Memory:
        """
        범용 메모리 추가 메서드 (하위 호환성 지원)
        
        Args:
            content: 저장할 내용
            context: 컨텍스트 정보
            importance: 중요도
            memory_type: 메모리 타입 ("episode", "short_term", "long_term")
        
        Returns:
            Memory: 생성된 메모리 객체
        """
        if memory_type == "short_term":
            return self.store_short_term(content, context, importance)
        elif memory_type == "long_term":
            return self.store_long_term(content, context, importance)
        else:  # 기본값은 episode
            # content가 dict가 아니면 dict로 변환
            if not isinstance(content, dict):
                content = {"data": content}
            
            # context 정보 추가
            if context:
                content.update(context)
                
            return self.store_episode(content)
    
    def recall(self, query: str, memory_types: List[MemoryType] = None) -> List[Memory]:
        """메모리 검색"""
        results = []
        
        if not memory_types:
            memory_types = [MemoryType.SHORT_TERM, MemoryType.LONG_TERM]
        
        # 단기 메모리 검색
        if MemoryType.SHORT_TERM in memory_types:
            stm_results = self.short_term.find(query)
            results.extend(stm_results)
        
        # 장기 메모리 검색
        if MemoryType.LONG_TERM in memory_types:
            ltm_results = self.long_term.find(query)
            results.extend(ltm_results)
        
        # 에피소드 메모리 검색
        if MemoryType.EPISODIC in memory_types:
            query_lower = query.lower()
            for memory in self.episodic_memories:
                if query_lower in str(memory.content).lower():
                    results.append(memory)
        
        # 결과를 강도순으로 정렬
        results.sort(key=lambda m: m.get_strength(), reverse=True)
        
        logger.info(f"Recalled {len(results)} memories for query: '{query}'")
        return results
    
    def get_fact(self, key: str) -> Optional[Any]:
        """의미 메모리 (사실) 조회"""
        if key in self.semantic_memories:
            return self.semantic_memories[key]["value"]
        return None
    
    def get_procedure(self, name: str) -> Optional[List[str]]:
        """절차 메모리 조회"""
        if name in self.procedural_memories:
            return self.procedural_memories[name]["steps"]
        return None
    
    def transfer_to_long_term(self) -> int:
        """단기 메모리를 장기 메모리로 전송"""
        transferred = 0
        
        for memory in self.short_term.get_all():
            # 중요도가 높거나 자주 접근된 메모리만 전송
            if (memory.importance.value >= MemoryImportance.MEDIUM.value or
                memory.access_count > 2):
                
                # 타입 변경
                memory.type = MemoryType.LONG_TERM
                if self.long_term.add(memory):
                    transferred += 1
        
        # 단기 메모리 초기화
        self.short_term.clear()
        
        logger.info(f"Transferred {transferred} memories to long-term storage")
        return transferred
    
    def consolidate(self):
        """메모리 통합 및 정리"""
        # 장기 메모리 통합
        self.long_term.consolidate()
        
        # 오래된 에피소드 메모리 정리
        cutoff_date = datetime.now() - timedelta(days=30)
        self.episodic_memories = [
            m for m in self.episodic_memories 
            if m.created_at > cutoff_date or m.importance.value >= MemoryImportance.HIGH.value
        ]
        
        logger.info("Memory consolidation completed")
    
    def create_associations(self, memory_id1: str, memory_id2: str):
        """두 메모리 간 연관 관계 생성"""
        memory1 = self.long_term.get(memory_id1)
        memory2 = self.long_term.get(memory_id2)
        
        if memory1 and memory2:
            if memory_id2 not in memory1.associations:
                memory1.associations.append(memory_id2)
            if memory_id1 not in memory2.associations:
                memory2.associations.append(memory_id1)
            
            logger.debug(f"Created association between {memory_id1} and {memory_id2}")
    
    def get_associated_memories(self, memory_id: str) -> List[Memory]:
        """연관된 메모리들 조회"""
        memory = self.long_term.get(memory_id)
        if not memory:
            return []
        
        associated = []
        for assoc_id in memory.associations:
            assoc_memory = self.long_term.get(assoc_id)
            if assoc_memory:
                associated.append(assoc_memory)
        
        return associated
    
    def get_statistics(self) -> Dict[str, Any]:
        """메모리 통계"""
        return {
            "short_term_count": len(self.short_term.memories),
            "short_term_capacity": self.short_term.capacity,
            "long_term_count": len(self.long_term.memories),
            "long_term_capacity": self.long_term.max_size,
            "episodic_count": len(self.episodic_memories),
            "semantic_count": len(self.semantic_memories),
            "procedural_count": len(self.procedural_memories),
            "total_memories": (
                len(self.short_term.memories) + 
                len(self.long_term.memories) +
                len(self.episodic_memories)
            )
        }
    
    def clear_all(self):
        """모든 메모리 초기화"""
        self.short_term.clear()
        self.long_term.memories.clear()
        self.long_term.index.clear()
        self.episodic_memories.clear()
        self.semantic_memories.clear()
        self.procedural_memories.clear()
        
        logger.info("All memories cleared")