"""
CollaborationService — 에이전트 간 협업 서비스 인터페이스

ACP 서버(또는 런타임)가 이 인터페이스를 구현하여
에이전트에 주입(inject)한다.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .models import (
    AgentCapability,
    CollaborationRequest,
    CollaborationResult,
    CollaborationStatus,
)
from .call_graph import GlobalCallGraph

if TYPE_CHECKING:
    from ..agent import LogosAIAgent

logger = logging.getLogger(__name__)


class CollaborationService(ABC):
    """
    에이전트 간 협업 서비스 추상 클래스.

    ACP 서버가 이 클래스를 구현하고,
    에이전트 로드 시 agent.set_collaboration_service(service)로 주입한다.
    """

    def __init__(self):
        self.call_graph = GlobalCallGraph.get_instance()

    @abstractmethod
    async def discover_agents(
        self, capability: str, exclude_ids: Optional[List[str]] = None
    ) -> List[AgentCapability]:
        """
        특정 능력을 가진 에이전트 목록 조회.

        Args:
            capability: 필요한 능력 (예: "translation", "document_processing")
            exclude_ids: 제외할 에이전트 ID 목록

        Returns:
            매칭된 에이전트 목록
        """

    @abstractmethod
    async def select_agent(
        self, capability: str, query: str, exclude_ids: Optional[List[str]] = None
    ) -> Optional[AgentCapability]:
        """
        주어진 능력과 쿼리에 가장 적합한 에이전트 선택.

        Args:
            capability: 필요한 능력
            query: 처리할 쿼리 (선택 시 참고)
            exclude_ids: 제외할 에이전트 ID 목록

        Returns:
            선택된 에이전트, 없으면 None
        """

    @abstractmethod
    async def _execute_on_agent(
        self, agent_id: str, query: str, context: Dict[str, Any]
    ) -> Any:
        """
        실제 에이전트에서 쿼리 실행.
        ACP 서버 구현에서 in-process 호출 또는 HTTP 호출.

        Args:
            agent_id: 대상 에이전트 ID
            query: 실행할 쿼리
            context: 실행 컨텍스트

        Returns:
            에이전트 실행 결과 (AgentResponse 또는 dict)
        """

    async def invoke(
        self,
        caller: LogosAIAgent,
        capability: str,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        parent_request: Optional[CollaborationRequest] = None,
    ) -> CollaborationResult:
        """
        다른 에이전트를 호출하여 협업 수행.

        내부적으로:
        1. 콜 그래프에서 루프/깊이 체크
        2. 적합한 에이전트 선택
        3. 타임아웃 적용하여 실행
        4. 결과 반환

        Args:
            caller: 호출하는 에이전트
            capability: 필요한 능력
            query: 처리할 쿼리
            context: 추가 컨텍스트
            timeout: 타임아웃 (초). None이면 점감 타임아웃 적용
            parent_request: 상위 요청 (체인 추적용)
        """
        start_time = time.time()
        context = context or {}

        # 요청 빌드
        if parent_request:
            depth = parent_request.depth + 1
            call_chain = parent_request.call_chain + [caller.id]
            parent_id = parent_request.request_id
            # 점감 타임아웃: 상위 타임아웃의 70%
            default_timeout = parent_request.timeout * 0.7
        else:
            depth = 0
            call_chain = [caller.id]
            parent_id = None
            default_timeout = 30.0

        effective_timeout = timeout if timeout is not None else default_timeout

        request = CollaborationRequest(
            caller_id=caller.id,
            caller_name=caller.name,
            capability=capability,
            query=query,
            context=context,
            timeout=effective_timeout,
            parent_request_id=parent_id,
            depth=depth,
            max_depth=self.call_graph._max_depth,
            call_chain=call_chain,
        )

        # 에이전트 선택
        selected = await self.select_agent(
            capability=capability,
            query=query,
            exclude_ids=call_chain,  # 콜 체인에 있는 에이전트 제외
        )

        if not selected:
            return CollaborationResult(
                request_id=request.request_id,
                status=CollaborationStatus.FAILED,
                error=f"No agent found for capability: {capability}",
                depth=depth,
                call_chain=call_chain,
            )

        # 콜 그래프 체크 + 추적
        async with self.call_graph.track_call(
            request_id=request.request_id,
            caller_id=caller.id,
            callee_id=selected.agent_id,
            call_chain=call_chain,
            depth=depth,
            parent_request_id=parent_id,
        ) as (can_proceed, error):
            if not can_proceed:
                status = CollaborationStatus.LOOP_DETECTED
                if "depth" in (error or "").lower():
                    status = CollaborationStatus.DEPTH_EXCEEDED
                return CollaborationResult(
                    request_id=request.request_id,
                    status=status,
                    agent_id=selected.agent_id,
                    agent_name=selected.agent_name,
                    error=error,
                    depth=depth,
                    call_chain=call_chain,
                )

            # 타임아웃 적용하여 실행
            exec_context = {
                **context,
                "_collaboration": {
                    "request_id": request.request_id,
                    "parent_request_id": parent_id,
                    "depth": depth,
                    "call_chain": call_chain + [selected.agent_id],
                    "timeout": effective_timeout,
                    "caller_id": caller.id,
                    "caller_name": caller.name,
                },
            }

            try:
                result = await asyncio.wait_for(
                    self._execute_on_agent(
                        agent_id=selected.agent_id,
                        query=query,
                        context=exec_context,
                    ),
                    timeout=effective_timeout,
                )

                elapsed = time.time() - start_time
                logger.info(
                    f"[Collaboration] {caller.name}→{selected.agent_name} "
                    f"completed in {elapsed:.2f}s (depth={depth})"
                )

                return CollaborationResult(
                    request_id=request.request_id,
                    status=CollaborationStatus.COMPLETED,
                    agent_id=selected.agent_id,
                    agent_name=selected.agent_name,
                    data=result,
                    execution_time=elapsed,
                    depth=depth,
                    call_chain=call_chain + [selected.agent_id],
                )

            except asyncio.TimeoutError:
                elapsed = time.time() - start_time
                logger.warning(
                    f"[Collaboration] TIMEOUT: {caller.name}→{selected.agent_name} "
                    f"after {elapsed:.2f}s (limit={effective_timeout}s)"
                )
                return CollaborationResult(
                    request_id=request.request_id,
                    status=CollaborationStatus.TIMEOUT,
                    agent_id=selected.agent_id,
                    agent_name=selected.agent_name,
                    error=f"Timeout after {effective_timeout}s",
                    execution_time=elapsed,
                    depth=depth,
                    call_chain=call_chain + [selected.agent_id],
                )

            except Exception as e:
                elapsed = time.time() - start_time
                logger.error(
                    f"[Collaboration] ERROR: {caller.name}→{selected.agent_name} "
                    f"| {type(e).__name__}: {e}"
                )
                return CollaborationResult(
                    request_id=request.request_id,
                    status=CollaborationStatus.FAILED,
                    agent_id=selected.agent_id,
                    agent_name=selected.agent_name,
                    error=str(e),
                    execution_time=elapsed,
                    depth=depth,
                    call_chain=call_chain + [selected.agent_id],
                )
