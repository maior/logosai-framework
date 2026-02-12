"""
LogosAI SDK 에이전트 구독 유틸리티

이 모듈은 에이전트가 메시지 버스에 쉽게 구독할 수 있는 유틸리티 함수들을 제공합니다.
"""

import asyncio
import logging
from typing import Dict, List, Any, Callable, Optional, Union
import inspect

from .message_bus_impl import MessageBus, Message, MessageType
from .message_types import AgentMessageType, WorkflowMessageType
from .topic_utils import create_agent_topic, parse_topic

# 로거 설정
logger = logging.getLogger(__name__)

# 메시지 핸들러 타입 정의
MessageHandler = Callable[[Message], Any]

async def subscribe_agent(
    agent_id: str,
    handler_map: Dict[str, MessageHandler],
    message_bus: Optional[MessageBus] = None,
    topics: Optional[List[str]] = None
) -> Dict[str, str]:
    """
    에이전트를 메시지 버스에 구독
    
    Args:
        agent_id: 에이전트 ID
        handler_map: 메시지 타입별 핸들러 함수 딕셔너리
        message_bus: 메시지 버스 인스턴스 (None이면 싱글톤 인스턴스 사용)
        topics: 구독할 토픽 리스트 (None이면 기본 토픽 사용)
        
    Returns:
        Dict[str, str]: 구독 ID 딕셔너리 (토픽별)
    """
    # 메시지 버스 가져오기
    if message_bus is None:
        message_bus = MessageBus()
    
    # 구독 ID 딕셔너리
    subscription_ids = {}
    
    # 기본 토픽 설정
    if topics is None:
        topics = [
            f"agent.{agent_id}.request",     # 에이전트 요청
            f"agent.{agent_id}.response",    # 에이전트 응답
            f"agent.{agent_id}.error",       # 에이전트 오류
            "agent.status"                   # 에이전트 상태 업데이트
        ]
    
    # 모든 토픽에 대해 구독
    for topic in topics:
        # 메시지 핸들러 정의
        async def message_handler(message: Message):
            try:
                # 토픽에서 메시지 타입 추출
                _, msg_type = parse_topic(message.topic)
                
                # 해당 메시지 타입의 핸들러가 있는지 확인
                if msg_type in handler_map:
                    handler = handler_map[msg_type]
                    
                    # 핸들러가 비동기 함수인지 확인
                    if inspect.iscoroutinefunction(handler):
                        await handler(message)
                    else:
                        handler(message)
                else:
                    logger.warning(f"에이전트 {agent_id}에 메시지 타입 '{msg_type}'에 대한 핸들러가 없습니다.")
            except Exception as e:
                logger.error(f"메시지 처리 중 오류: {str(e)}")
        
        # 구독 등록
        subscription_id = await message_bus.subscribe(
            topic_pattern=topic,
            callback=message_handler,
            subscriber_id=agent_id
        )
        
        subscription_ids[topic] = subscription_id
        logger.info(f"에이전트 {agent_id}가 토픽 '{topic}'에 구독했습니다. (구독 ID: {subscription_id})")
    
    return subscription_ids

async def unsubscribe_agent(
    agent_id: str,
    subscription_ids: Optional[List[str]] = None,
    message_bus: Optional[MessageBus] = None
) -> bool:
    """
    에이전트의 구독 해제
    
    Args:
        agent_id: 에이전트 ID
        subscription_ids: 구독 ID 리스트 (None이면 모든 구독 해제)
        message_bus: 메시지 버스 인스턴스 (None이면 싱글톤 인스턴스 사용)
        
    Returns:
        bool: 성공 여부
    """
    # 메시지 버스 가져오기
    if message_bus is None:
        message_bus = MessageBus()
    
    try:
        # 특정 구독 ID만 해제
        if subscription_ids:
            for subscription_id in subscription_ids:
                await message_bus.unsubscribe(subscription_id=subscription_id)
                logger.info(f"구독 ID {subscription_id}가 해제되었습니다.")
        # 에이전트의 모든 구독 해제
        else:
            await message_bus.unsubscribe(subscriber_id=agent_id)
            logger.info(f"에이전트 {agent_id}의 모든 구독이 해제되었습니다.")
        
        return True
    except Exception as e:
        logger.error(f"구독 해제 중 오류: {str(e)}")
        return False

def register_handler(
    handler_map: Dict[str, MessageHandler],
    message_type: Union[str, AgentMessageType, WorkflowMessageType],
    handler: MessageHandler
) -> Dict[str, MessageHandler]:
    """
    메시지 타입에 대한 핸들러 등록
    
    Args:
        handler_map: 기존 핸들러 맵
        message_type: 메시지 타입
        handler: 핸들러 함수
        
    Returns:
        Dict[str, MessageHandler]: 업데이트된 핸들러 맵
    """
    # 메시지 타입이 열거형인 경우 문자열로 변환
    if isinstance(message_type, (AgentMessageType, WorkflowMessageType)):
        message_type = message_type.value
    
    # 핸들러 등록
    handler_map[message_type] = handler
    logger.debug(f"메시지 타입 '{message_type}'에 대한 핸들러가 등록되었습니다.")
    
    return handler_map

# 에이전트 클래스를 위한 데코레이터
def message_handler(message_type: Union[str, AgentMessageType, WorkflowMessageType]):
    """
    메시지 핸들러 데코레이터
    
    Args:
        message_type: 처리할 메시지 타입
        
    Returns:
        Callable: 데코레이터 함수
    """
    def decorator(func):
        # 메시지 타입이 열거형인 경우 문자열로 변환
        if isinstance(message_type, (AgentMessageType, WorkflowMessageType)):
            func._message_type = message_type.value
        else:
            func._message_type = message_type
        
        return func
    
    return decorator 