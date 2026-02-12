"""
메시지 버스 모듈

이 모듈은 LogosAI의 메시지 버스 기능을 제공합니다.
"""

from .message_bus_impl import MessageBus, Message, MessageType, MessagePriority
from .message_types import AgentMessageType, WorkflowMessageType
from .subscription_manager import MessageSubscriptionManager, get_subscription_manager
from .agent_subscription import subscribe_agent, unsubscribe_agent, register_handler
from .topic_utils import create_agent_topic, create_workflow_topic, parse_topic, get_standard_topics


async def subscribe_to_topic(topic: str, handler, message_bus: MessageBus = None):
    """
    토픽에 구독하는 헬퍼 함수

    Args:
        topic: 구독할 토픽
        handler: 메시지 핸들러 함수
        message_bus: 메시지 버스 인스턴스 (None이면 싱글톤 인스턴스 사용)
    """
    if message_bus is None:
        message_bus = MessageBus()
    await message_bus.subscribe(topic, handler)


__all__ = [
    # Core message bus
    'MessageBus',
    'Message',
    'MessageType',
    'MessagePriority',
    # Message types
    'AgentMessageType',
    'WorkflowMessageType',
    # Subscription management
    'MessageSubscriptionManager',
    'get_subscription_manager',
    # Agent subscription
    'subscribe_agent',
    'unsubscribe_agent',
    'register_handler',
    # Topic utilities
    'create_agent_topic',
    'create_workflow_topic',
    'parse_topic',
    'get_standard_topics',
    # Helper functions
    'subscribe_to_topic',
]
