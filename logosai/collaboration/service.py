"""
CollaborationService — Inter-agent collaboration service interface

The ACP server (or runtime) implements this interface
and injects it into agents.
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
    Abstract class for inter-agent collaboration service.

    The ACP server implements this class and
    injects it via agent.set_collaboration_service(service) when loading agents.
    """

    def __init__(self):
        self.call_graph = GlobalCallGraph.get_instance()

    @abstractmethod
    async def discover_agents(
        self, capability: str, exclude_ids: Optional[List[str]] = None
    ) -> List[AgentCapability]:
        """
        Query list of agents with specific capability.

        Args:
            capability: Required capability (e.g., "translation", "document_processing")
            exclude_ids: List of agent IDs to exclude

        Returns:
            List of matched agents
        """

    @abstractmethod
    async def select_agent(
        self, capability: str, query: str, exclude_ids: Optional[List[str]] = None
    ) -> Optional[AgentCapability]:
        """
        Select the most suitable agent for given capability and query.

        Args:
            capability: Required capability
            query: Query to process (used as reference for selection)
            exclude_ids: List of agent IDs to exclude

        Returns:
            Selected agent, or None if not found
        """

    @abstractmethod
    async def _execute_on_agent(
        self, agent_id: str, query: str, context: Dict[str, Any]
    ) -> Any:
        """
        Execute query on actual agent.
        In ACP server implementation, use in-process or HTTP call.

        Args:
            agent_id: Target agent ID
            query: Query to execute
            context: Execution context

        Returns:
            Agent execution result (AgentResponse or dict)
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
        Perform collaboration by calling another agent.

        Internally:
        1. Check loop/depth in call graph
        2. Select suitable agent
        3. Execute with timeout
        4. Return result

        Args:
            caller: Calling agent
            capability: Required capability
            query: Query to process
            context: Additional context
            timeout: Timeout in seconds. If None, applies decreasing timeout
            parent_request: Parent request (for chain tracking)
        """
        start_time = time.time()
        context = context or {}

        # Build request
        if parent_request:
            depth = parent_request.depth + 1
            call_chain = parent_request.call_chain + [caller.id]
            parent_id = parent_request.request_id
            # Decreasing timeout: 70% of parent timeout
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

        # Agent selection
        selected = await self.select_agent(
            capability=capability,
            query=query,
            exclude_ids=call_chain,  # Exclude agents in call chain
        )

        if not selected:
            return CollaborationResult(
                request_id=request.request_id,
                status=CollaborationStatus.FAILED,
                error=f"No agent found for capability: {capability}",
                depth=depth,
                call_chain=call_chain,
            )

        # Call graph check + tracking
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

            # Execute with timeout
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
