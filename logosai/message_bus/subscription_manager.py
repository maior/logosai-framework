"""
LogosAI SDK 메시지 구독 관리 모듈

이 모듈은 LogosAI SDK의 메시지 구독을 관리하는 클래스와 유틸리티를 제공합니다.
"""

import json
import os
import logging
import uuid
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional, Callable, Set

from .message_bus_impl import MessageBus, Message
from .topic_utils import get_standard_topics

# 로깅 설정
logger = logging.getLogger(__name__)

class MessageSubscriptionManager:
    """메시지 구독 관리 클래스
    
    에이전트 시스템의 메시지 구독을 관리하고 JSON 파일로 저장합니다.
    구독 추가, 제거, 활성화, 비활성화 기능을 제공합니다.
    """
    
    _instance = None  # 싱글톤 패턴을 위한 인스턴스
    
    def __new__(cls, config_dir=None):
        """싱글톤 패턴 구현"""
        if cls._instance is None:
            cls._instance = super(MessageSubscriptionManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, config_dir=None):
        """초기화"""
        if self._initialized:
            return
            
        # 구독 정보 저장 경로
        if config_dir:
            self.config_dir = config_dir
        else:
            self.config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config")
            
        self.subscription_file = os.path.join(self.config_dir, "message_subscriptions.json")
        
        # 구독 정보 딕셔너리
        self.subscriptions = {}
        
        # 활성 구독 캐시
        self.active_subscriptions = {}
        
        # 메시지 버스 인스턴스
        self.message_bus = None
        
        # 구독 정보 로드
        self.load_subscriptions()
        
        self._initialized = True
        logger.info("MessageSubscriptionManager 초기화 완료")
    
    def set_message_bus(self, message_bus: MessageBus):
        """메시지 버스 설정"""
        self.message_bus = message_bus
        logger.debug("메시지 버스가 설정되었습니다.")
    
    def load_subscriptions(self) -> bool:
        """구독 정보 파일 로드"""
        try:
            if os.path.exists(self.subscription_file):
                with open(self.subscription_file, 'r', encoding='utf-8') as f:
                    self.subscriptions = json.load(f)
                logger.info(f"{len(self.subscriptions)} 개의 구독 정보를 로드했습니다.")
                
                # 활성 구독 캐시 업데이트
                self.active_subscriptions = {
                    sub_id: sub for sub_id, sub in self.subscriptions.items() 
                    if sub.get("active", True)
                }
                
                return True
            else:
                logger.info("구독 정보 파일이 없습니다. 새로 생성합니다.")
                self.subscriptions = {}
                self.active_subscriptions = {}
                self.save_subscriptions()
                return True
        except Exception as e:
            logger.error(f"구독 정보 로드 중 오류: {str(e)}")
            return False
    
    def save_subscriptions(self) -> bool:
        """구독 정보 파일 저장"""
        try:
            # 디렉토리 생성 (없는 경우)
            os.makedirs(self.config_dir, exist_ok=True)
            
            with open(self.subscription_file, 'w', encoding='utf-8') as f:
                json.dump(self.subscriptions, f, indent=2, ensure_ascii=False)
            logger.info(f"{len(self.subscriptions)} 개의 구독 정보를 저장했습니다.")
            return True
        except Exception as e:
            logger.error(f"구독 정보 저장 중 오류: {str(e)}")
            return False
    
    def add_subscription(self, subscription_info: Dict[str, Any]) -> bool:
        """구독 추가"""
        try:
            # 필수 필드 확인
            required_fields = ["subscription_id", "subscriber_id", "topic_pattern"]
            for field in required_fields:
                if field not in subscription_info:
                    logger.error(f"구독 정보에 필수 필드 '{field}'가 없습니다.")
                    return False
            
            # 구독 ID가 이미 존재하는 경우
            subscription_id = subscription_info["subscription_id"]
            if subscription_id in self.subscriptions:
                logger.warning(f"구독 ID '{subscription_id}'가 이미 존재합니다. 덮어씁니다.")
            
            # 구독 정보 추가
            subscription_info["active"] = subscription_info.get("active", True)
            subscription_info["created_at"] = subscription_info.get("created_at", datetime.now().isoformat())
            subscription_info["updated_at"] = datetime.now().isoformat()
            
            self.subscriptions[subscription_id] = subscription_info
            
            # 활성 구독인 경우 캐시 업데이트
            if subscription_info["active"]:
                self.active_subscriptions[subscription_id] = subscription_info
            
            # 저장
            self.save_subscriptions()
            
            logger.info(f"구독 '{subscription_id}'가 추가되었습니다.")
            return True
        except Exception as e:
            logger.error(f"구독 추가 중 오류: {str(e)}")
            return False
    
    def remove_subscription(self, subscription_id: str) -> bool:
        """구독 제거"""
        try:
            if subscription_id not in self.subscriptions:
                logger.warning(f"구독 ID '{subscription_id}'를 찾을 수 없습니다.")
                return False
            
            # 구독 제거
            del self.subscriptions[subscription_id]
            
            # 활성 구독 캐시에서도 제거
            if subscription_id in self.active_subscriptions:
                del self.active_subscriptions[subscription_id]
            
            # 저장
            self.save_subscriptions()
            
            logger.info(f"구독 '{subscription_id}'가 제거되었습니다.")
            return True
        except Exception as e:
            logger.error(f"구독 제거 중 오류: {str(e)}")
            return False
    
    def activate_subscription(self, subscription_id: str) -> bool:
        """구독 활성화"""
        try:
            if subscription_id not in self.subscriptions:
                logger.warning(f"구독 ID '{subscription_id}'를 찾을 수 없습니다.")
                return False
            
            # 구독 활성화
            self.subscriptions[subscription_id]["active"] = True
            self.subscriptions[subscription_id]["updated_at"] = datetime.now().isoformat()
            
            # 활성 구독 캐시 업데이트
            self.active_subscriptions[subscription_id] = self.subscriptions[subscription_id]
            
            # 저장
            self.save_subscriptions()
            
            logger.info(f"구독 '{subscription_id}'가 활성화되었습니다.")
            return True
        except Exception as e:
            logger.error(f"구독 활성화 중 오류: {str(e)}")
            return False
    
    def deactivate_subscription(self, subscription_id: str) -> bool:
        """구독 비활성화"""
        try:
            if subscription_id not in self.subscriptions:
                logger.warning(f"구독 ID '{subscription_id}'를 찾을 수 없습니다.")
                return False
            
            # 구독 비활성화
            self.subscriptions[subscription_id]["active"] = False
            self.subscriptions[subscription_id]["updated_at"] = datetime.now().isoformat()
            
            # 활성 구독 캐시에서 제거
            if subscription_id in self.active_subscriptions:
                del self.active_subscriptions[subscription_id]
            
            # 저장
            self.save_subscriptions()
            
            logger.info(f"구독 '{subscription_id}'가 비활성화되었습니다.")
            return True
        except Exception as e:
            logger.error(f"구독 비활성화 중 오류: {str(e)}")
            return False
    
    def get_subscription(self, subscription_id: str) -> Optional[Dict[str, Any]]:
        """구독 정보 조회"""
        return self.subscriptions.get(subscription_id)
    
    def get_subscriptions_by_subscriber(self, subscriber_id: str) -> List[Dict[str, Any]]:
        """구독자별 구독 정보 조회"""
        return [
            subscription
            for subscription_id, subscription in self.subscriptions.items()
            if subscription["subscriber_id"] == subscriber_id
        ]
    
    def get_subscriptions_by_topic(self, topic_pattern: str) -> List[Dict[str, Any]]:
        """토픽별 구독 정보 조회"""
        return [
            subscription
            for subscription_id, subscription in self.subscriptions.items()
            if subscription["topic_pattern"] == topic_pattern
        ]
    
    def get_active_subscriptions(self) -> Dict[str, Dict[str, Any]]:
        """활성화된 구독 정보 조회"""
        return self.active_subscriptions
    
    def get_all_subscriptions(self) -> Dict[str, Dict[str, Any]]:
        """모든 구독 정보 조회"""
        return self.subscriptions
    
    def create_subscription(self, subscriber_id: str, topic_pattern: str, metadata: Dict[str, Any] = None) -> str:
        """구독 생성 헬퍼 함수"""
        try:
            # 구독 ID 생성
            subscription_id = f"{subscriber_id}_{topic_pattern.replace('.', '_').replace('*', 'X').replace('#', 'H')}_{uuid.uuid4().hex[:6]}"
            
            # 구독 정보 생성
            subscription_info = {
                "subscription_id": subscription_id,
                "subscriber_id": subscriber_id,
                "topic_pattern": topic_pattern,
                "active": True,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }
            
            # 메타데이터 추가 (있는 경우)
            if metadata:
                subscription_info["metadata"] = metadata
            
            # 구독 추가
            if self.add_subscription(subscription_info):
                return subscription_id
            else:
                return ""
        except Exception as e:
            logger.error(f"구독 생성 중 오류: {str(e)}")
            return ""
    
    def unsubscribe(self, subscriber_id: str, topic_pattern: str = None) -> int:
        """구독 해제 헬퍼 함수
        
        Args:
            subscriber_id: 구독자 ID
            topic_pattern: 토픽 패턴 (None인 경우 구독자의 모든 구독 해제)
            
        Returns:
            int: 해제된 구독 수
        """
        try:
            # 구독자의 구독 정보 조회
            subscriptions = self.get_subscriptions_by_subscriber(subscriber_id)
            
            # 토픽 패턴이 있는 경우 필터링
            if topic_pattern:
                subscriptions = [
                    subscription
                    for subscription in subscriptions
                    if subscription["topic_pattern"] == topic_pattern
                ]
            
            # 구독 해제
            count = 0
            for subscription in subscriptions:
                if self.remove_subscription(subscription["subscription_id"]):
                    count += 1
            
            logger.info(f"구독자 '{subscriber_id}'의 {count}개 구독이 해제되었습니다.")
            return count
        except Exception as e:
            logger.error(f"구독 해제 중 오류: {str(e)}")
            return 0
    
    def get_subscriber_count(self) -> int:
        """구독자 수 조회"""
        subscriber_set = set()
        for subscription in self.subscriptions.values():
            subscriber_set.add(subscription["subscriber_id"])
        return len(subscriber_set)
    
    def get_active_subscriber_count(self) -> int:
        """활성 구독자 수 조회"""
        subscriber_set = set()
        for subscription in self.active_subscriptions.values():
            subscriber_set.add(subscription["subscriber_id"])
        return len(subscriber_set)
    
    def get_topic_count(self) -> int:
        """토픽 수 조회"""
        topic_set = set()
        for subscription in self.subscriptions.values():
            topic_set.add(subscription["topic_pattern"])
        return len(topic_set)
    
    def get_metrics(self) -> Dict[str, Any]:
        """메트릭 조회"""
        return {
            "total_subscriptions": len(self.subscriptions),
            "active_subscriptions": len(self.active_subscriptions),
            "subscriber_count": self.get_subscriber_count(),
            "active_subscriber_count": self.get_active_subscriber_count(),
            "topic_count": self.get_topic_count()
        }
    
    # 표준 구독 패턴을 위한 유틸리티 메서드
    
    async def subscribe_to_workflow_events(self, subscriber_id: str, workflow_id: str = None, message_bus: MessageBus = None) -> List[str]:
        """워크플로우 이벤트 구독
        
        Args:
            subscriber_id: 구독자 ID
            workflow_id: 워크플로우 ID (None이면 모든 워크플로우)
            message_bus: 메시지 버스 인스턴스
            
        Returns:
            List[str]: 생성된 구독 ID 목록
        """
        try:
            # 메시지 버스 설정
            if message_bus:
                self.message_bus = message_bus
            
            if not self.message_bus:
                self.message_bus = MessageBus()
            
            # 워크플로우 토픽 목록
            standard_topics = get_standard_topics()
            workflow_topics = standard_topics["workflow"]
            
            # 특정 워크플로우에 대한 토픽으로 변환
            if workflow_id:
                workflow_topics = [
                    topic.replace("<workflow_id>", workflow_id)
                    for topic in workflow_topics
                ]
            else:
                # 모든 워크플로우에 대한 와일드카드 토픽
                workflow_topics = [
                    topic.replace("<workflow_id>", "*").replace("<node_id>", "*")
                    for topic in workflow_topics
                ]
            
            # 메타데이터 설정
            metadata = {
                "category": "workflow",
                "auto_created": True
            }
            if workflow_id:
                metadata["workflow_id"] = workflow_id
            
            # 구독 ID 목록
            subscription_ids = []
            
            # 구독 생성 및 등록
            for topic in workflow_topics:
                # 메시지 버스에 구독
                async def message_handler(message: Message):
                    # 구독 핸들러 구현
                    logger.debug(f"워크플로우 이벤트 수신: {message.topic}")
                    
                subscription_id = await self.message_bus.subscribe(
                    topic_pattern=topic,
                    callback=message_handler,
                    subscriber_id=subscriber_id
                )
                
                # 구독 정보 저장
                sub_info = {
                    "subscription_id": subscription_id,
                    "subscriber_id": subscriber_id,
                    "topic_pattern": topic,
                    "active": True,
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "metadata": metadata
                }
                
                self.add_subscription(sub_info)
                subscription_ids.append(subscription_id)
                
            logger.info(f"구독자 '{subscriber_id}'의 {len(subscription_ids)}개 워크플로우 이벤트 구독이 생성되었습니다.")
            return subscription_ids
            
        except Exception as e:
            logger.error(f"워크플로우 이벤트 구독 중 오류: {str(e)}")
            return []
    
    async def subscribe_to_agent_events(self, subscriber_id: str, agent_id: str = None, message_bus: MessageBus = None) -> List[str]:
        """에이전트 이벤트 구독
        
        Args:
            subscriber_id: 구독자 ID
            agent_id: 에이전트 ID (None이면 모든 에이전트)
            message_bus: 메시지 버스 인스턴스
            
        Returns:
            List[str]: 생성된 구독 ID 목록
        """
        try:
            # 메시지 버스 설정
            if message_bus:
                self.message_bus = message_bus
            
            if not self.message_bus:
                self.message_bus = MessageBus()
            
            # 에이전트 토픽 목록
            standard_topics = get_standard_topics()
            agent_topics = standard_topics["agent"]
            
            # 특정 에이전트에 대한 토픽으로 변환
            if agent_id:
                agent_topics = [
                    topic.replace("<agent_id>", agent_id)
                    for topic in agent_topics
                ]
            else:
                # 모든 에이전트에 대한 와일드카드 토픽
                agent_topics = [
                    topic.replace("<agent_id>", "*")
                    for topic in agent_topics
                ]
            
            # 메타데이터 설정
            metadata = {
                "category": "agent",
                "auto_created": True
            }
            if agent_id:
                metadata["agent_id"] = agent_id
            
            # 구독 ID 목록
            subscription_ids = []
            
            # 구독 생성 및 등록
            for topic in agent_topics:
                # 메시지 버스에 구독
                async def message_handler(message: Message):
                    # 구독 핸들러 구현
                    logger.debug(f"에이전트 이벤트 수신: {message.topic}")
                    
                subscription_id = await self.message_bus.subscribe(
                    topic_pattern=topic,
                    callback=message_handler,
                    subscriber_id=subscriber_id
                )
                
                # 구독 정보 저장
                sub_info = {
                    "subscription_id": subscription_id,
                    "subscriber_id": subscriber_id,
                    "topic_pattern": topic,
                    "active": True,
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat(),
                    "metadata": metadata
                }
                
                self.add_subscription(sub_info)
                subscription_ids.append(subscription_id)
                
            logger.info(f"구독자 '{subscriber_id}'의 {len(subscription_ids)}개 에이전트 이벤트 구독이 생성되었습니다.")
            return subscription_ids
            
        except Exception as e:
            logger.error(f"에이전트 이벤트 구독 중 오류: {str(e)}")
            return []

# 싱글톤 인스턴스 가져오기
def get_subscription_manager(config_dir: str = None) -> MessageSubscriptionManager:
    """구독 관리자 싱글톤 인스턴스 가져오기"""
    return MessageSubscriptionManager(config_dir) 