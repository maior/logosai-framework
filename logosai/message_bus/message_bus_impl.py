"""
메시지 버스 모듈

이 모듈은 에이전트 간 메시지 교환을 위한 메시지 버스 구현을 제공합니다.
"""

import logging
import asyncio
import uuid
import re
import time
from typing import Any, Dict, List, Optional, Callable, Set, Union, Tuple, Awaitable
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime

# 로깅 설정
logger = logging.getLogger(__name__)


class MessageType(Enum):
    """메시지 유형 열거형"""
    EVENT = "event"         # 이벤트 알림
    REQUEST = "request"     # 요청
    RESPONSE = "response"   # 응답
    STATUS = "status"       # 상태 업데이트
    DATA = "data"           # 데이터 전송
    ERROR = "error"         # 오류 알림
    COMMAND = "command"     # 명령


class MessagePriority(Enum):
    """메시지 우선순위 열거형"""
    LOW = 0        # 낮은 우선순위
    NORMAL = 1     # 일반 우선순위
    HIGH = 2       # 높은 우선순위
    URGENT = 3     # 긴급 우선순위


@dataclass
class Message:
    """메시지 데이터 클래스"""
    topic: str
    data: Any
    sender: str = "system"
    timestamp: datetime = None
    
    def __post_init__(self):
        """초기화 후처리: 타임스탬프가 없으면 현재 시간으로 설정"""
        if self.timestamp is None:
            self.timestamp = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """메시지를 딕셔너리로 변환"""
        return {
            "topic": self.topic,
            "data": self.data,
            "sender": self.sender,
            "timestamp": self.timestamp.isoformat()
        }


# 메시지 핸들러 타입: Message를 받아 처리하는 함수
MessageHandler = Callable[[Message], Awaitable[None]]


class MessageBus:
    """메시지 버스 클래스
    
    에이전트 간 메시지 교환을 위한 간단한 게시-구독 패턴 구현
    """
    
    _instance = None  # 싱글톤 인스턴스
    
    def __new__(cls):
        """싱글톤 패턴 구현"""
        if cls._instance is None:
            cls._instance = super(MessageBus, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        """메시지 버스 초기화"""
        if not self._initialized:
            self.subscribers: Dict[str, Set[MessageHandler]] = {}
            self.message_history: List[Message] = []
            self.max_history: int = 100
            self.running: bool = False
            self.lock = asyncio.Lock()
            self._initialized = True
    
    async def start(self) -> None:
        """메시지 버스 시작"""
        async with self.lock:
            self.running = True
        logger.info("메시지 버스가 시작되었습니다.")
    
    async def stop(self) -> None:
        """메시지 버스 중지"""
        async with self.lock:
            self.running = False
        logger.info("메시지 버스가 중지되었습니다.")
    
    async def subscribe(self, topic: str, handler: MessageHandler) -> None:
        """토픽 구독
        
        Args:
            topic: 구독할 토픽 이름
            handler: 메시지를 처리할 핸들러 함수
        """
        async with self.lock:
            if topic not in self.subscribers:
                self.subscribers[topic] = set()
            self.subscribers[topic].add(handler)
        logger.debug(f"'{topic}' 토픽에 새로운 구독자가 추가되었습니다.")
    
    async def unsubscribe(self, topic: str, handler: MessageHandler) -> None:
        """토픽 구독 취소
        
        Args:
            topic: 구독 취소할 토픽 이름
            handler: 제거할 핸들러 함수
        """
        async with self.lock:
            if topic in self.subscribers and handler in self.subscribers[topic]:
                self.subscribers[topic].remove(handler)
                if not self.subscribers[topic]:
                    del self.subscribers[topic]
        logger.debug(f"'{topic}' 토픽에서 구독자가 제거되었습니다.")
    
    async def publish(
        self, 
        topic: str, 
        data: Any, 
        sender: str = "system"
    ) -> None:
        """메시지 발행
        
        Args:
            topic: 발행할 토픽 이름
            data: 전송할 데이터
            sender: 발신자 식별자
        """
        if not self.running:
            logger.warning("메시지 버스가 실행 중이 아닙니다. 메시지 발행이 무시됩니다.")
            return
        
        message = Message(topic=topic, data=data, sender=sender)
        
        # 메시지 이력에 추가
        async with self.lock:
            self.message_history.append(message)
            # 최대 이력 크기 유지
            if len(self.message_history) > self.max_history:
                self.message_history = self.message_history[-self.max_history:]
        
        # 구독자에게 메시지 전달
        handlers = set()
        async with self.lock:
            # 정확한 토픽 매칭
            if topic in self.subscribers:
                handlers.update(self.subscribers[topic])
            
            # 와일드카드 토픽 매칭
            for subscribed_topic, topic_handlers in self.subscribers.items():
                if self._match_wildcard_topic(subscribed_topic, topic):
                    handlers.update(topic_handlers)
        
        # 모든 핸들러에게 비동기로 메시지 전달
        if handlers:
            await asyncio.gather(*[
                self._safe_call_handler(handler, message)
                for handler in handlers
            ])
        
        logger.debug(f"토픽 '{topic}'에 메시지가 발행되었습니다: {data}")
    
    async def _safe_call_handler(
        self, 
        handler: MessageHandler, 
        message: Message
    ) -> None:
        """안전하게 핸들러 호출
        
        예외가 발생해도 다른 핸들러에 영향을 주지 않음
        
        Args:
            handler: 호출할 핸들러 함수
            message: 전달할 메시지
        """
        try:
            await handler(message)
        except Exception as e:
            logger.error(f"메시지 핸들러 실행 중 오류 발생: {str(e)}")
    
    def _match_wildcard_topic(self, pattern: str, topic: str) -> bool:
        """와일드카드 토픽 매칭 검사
        
        Args:
            pattern: 와일드카드를 포함할 수 있는 구독 패턴
            topic: 실제 메시지 토픽
            
        Returns:
            매칭 여부
        """
        if pattern == '#':  # 모든 토픽 매칭
            return True
        
        pattern_parts = pattern.split('/')
        topic_parts = topic.split('/')
            
        # 패턴이 '#'으로 끝나면 토픽 앞부분만 매칭
        if pattern_parts[-1] == '#':
            if len(pattern_parts) > len(topic_parts) + 1:
                return False
            
            for i in range(len(pattern_parts) - 1):
                if i >= len(topic_parts):
                    return False
                
                if pattern_parts[i] != '+' and pattern_parts[i] != topic_parts[i]:
                    return False
            
            return True
        
        # '+' 매칭 처리
        if len(pattern_parts) != len(topic_parts):
            return False
        
        for p, t in zip(pattern_parts, topic_parts):
            if p != '+' and p != t:
                return False
        
        return True
    
    def get_message_history(
        self, 
        topic: Optional[str] = None, 
        sender: Optional[str] = None,
        limit: int = 10
    ) -> List[Message]:
        """메시지 이력 조회
        
        Args:
            topic: 필터링할 토픽 (선택 사항)
            sender: 필터링할 발신자 (선택 사항)
            limit: 반환할 최대 메시지 수
            
        Returns:
            필터링된 메시지 목록
        """
        filtered = self.message_history
        
        if topic:
            filtered = [msg for msg in filtered if msg.topic == topic]
        
        if sender:
            filtered = [msg for msg in filtered if msg.sender == sender]
        
        return filtered[-limit:]
    
    def get_status(self) -> Dict[str, Any]:
        """메시지 버스 상태 정보"""
        return {
            "running": self.running,
            "message_count": len(self.message_history),
            "topic_count": len(self.subscribers),
            "subscriber_count": len(self.subscribers),
            "subscription_count": len(self.subscribers),
            "pending_requests": 0
        }
    
    def get_topic_count(self) -> int:
        """활성 토픽 수"""
        return len(self.subscribers)
    
    def get_subscriber_count(self) -> int:
        """구독자 수"""
        return len(self.subscribers) 