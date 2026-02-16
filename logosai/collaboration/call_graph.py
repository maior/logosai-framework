"""
Global Call Graph — 에이전트 간 호출 추적 및 루프 방지

싱글톤으로 동작하여 모든 에이전트 간 호출을 중앙에서 추적.
순환 호출 탐지, 최대 깊이 제한, 타임아웃 체이닝을 담당.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


@dataclass
class CallRecord:
    """개별 호출 기록"""
    request_id: str
    caller_id: str
    callee_id: str
    depth: int
    started_at: float = field(default_factory=time.time)
    parent_request_id: Optional[str] = None


class GlobalCallGraph:
    """
    글로벌 콜 그래프 — 싱글톤

    모든 에이전트 간 호출을 추적하여:
    1. 순환 호출 탐지 (A→B→A)
    2. 최대 깊이 제한 (기본 5)
    3. 활성 호출 추적 (동시성 관리)
    """

    _instance: Optional[GlobalCallGraph] = None
    _lock: asyncio.Lock = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._active_calls: Dict[str, CallRecord] = {}  # request_id → CallRecord
        self._agent_active_chains: Dict[str, Set[str]] = {}  # agent_id → {request_ids 참여 중}
        self._max_depth: int = 5
        self._max_concurrent_chains: int = 20
        self._initialized = True

    @classmethod
    def get_instance(cls) -> GlobalCallGraph:
        return cls()

    @classmethod
    def reset(cls):
        """테스트용: 싱글톤 초기화"""
        if cls._instance is not None:
            cls._instance._active_calls.clear()
            cls._instance._agent_active_chains.clear()

    def set_max_depth(self, depth: int):
        self._max_depth = depth

    def check_can_call(
        self,
        caller_id: str,
        callee_id: str,
        call_chain: List[str],
        depth: int
    ) -> Tuple[bool, Optional[str]]:
        """
        호출 가능 여부 검증.

        Returns:
            (can_call, error_reason)
        """
        # 1. 깊이 제한 체크
        if depth >= self._max_depth:
            reason = f"Max depth {self._max_depth} exceeded (current: {depth})"
            logger.warning(f"[CallGraph] DEPTH_EXCEEDED: {caller_id}→{callee_id} | {reason}")
            return False, reason

        # 2. 순환 호출 체크: callee가 이미 call_chain에 있으면 루프
        if callee_id in call_chain:
            chain_str = " → ".join(call_chain + [callee_id])
            reason = f"Loop detected: {chain_str}"
            logger.warning(f"[CallGraph] LOOP_DETECTED: {reason}")
            return False, reason

        # 3. 자기 자신 호출 체크
        if caller_id == callee_id:
            reason = f"Self-call detected: {caller_id}→{callee_id}"
            logger.warning(f"[CallGraph] SELF_CALL: {reason}")
            return False, reason

        # 4. 동시 체인 수 제한
        if len(self._active_calls) >= self._max_concurrent_chains:
            reason = f"Too many concurrent chains ({len(self._active_calls)}/{self._max_concurrent_chains})"
            logger.warning(f"[CallGraph] CONCURRENT_LIMIT: {reason}")
            return False, reason

        return True, None

    def enter_call(
        self,
        request_id: str,
        caller_id: str,
        callee_id: str,
        depth: int,
        parent_request_id: Optional[str] = None
    ):
        """호출 진입 기록"""
        record = CallRecord(
            request_id=request_id,
            caller_id=caller_id,
            callee_id=callee_id,
            depth=depth,
            parent_request_id=parent_request_id
        )
        self._active_calls[request_id] = record

        # 에이전트별 활성 체인 추적
        for agent_id in (caller_id, callee_id):
            if agent_id not in self._agent_active_chains:
                self._agent_active_chains[agent_id] = set()
            self._agent_active_chains[agent_id].add(request_id)

        logger.debug(
            f"[CallGraph] ENTER: {caller_id}→{callee_id} "
            f"(depth={depth}, request={request_id[:8]})"
        )

    def exit_call(self, request_id: str):
        """호출 종료 기록"""
        record = self._active_calls.pop(request_id, None)
        if record:
            # 에이전트별 활성 체인에서 제거
            for agent_id in (record.caller_id, record.callee_id):
                if agent_id in self._agent_active_chains:
                    self._agent_active_chains[agent_id].discard(request_id)
                    if not self._agent_active_chains[agent_id]:
                        del self._agent_active_chains[agent_id]

            elapsed = time.time() - record.started_at
            logger.debug(
                f"[CallGraph] EXIT: {record.caller_id}→{record.callee_id} "
                f"(depth={record.depth}, elapsed={elapsed:.2f}s)"
            )

    @asynccontextmanager
    async def track_call(
        self,
        request_id: str,
        caller_id: str,
        callee_id: str,
        call_chain: List[str],
        depth: int,
        parent_request_id: Optional[str] = None
    ):
        """
        컨텍스트 매니저로 호출 추적.

        Usage:
            async with call_graph.track_call(...) as can_proceed:
                if can_proceed:
                    result = await target_agent.process(query)
        """
        can_call, error = self.check_can_call(caller_id, callee_id, call_chain, depth)

        if not can_call:
            yield False, error
            return

        self.enter_call(request_id, caller_id, callee_id, depth, parent_request_id)
        try:
            yield True, None
        finally:
            self.exit_call(request_id)

    def get_active_calls_count(self) -> int:
        return len(self._active_calls)

    def get_agent_active_count(self, agent_id: str) -> int:
        return len(self._agent_active_chains.get(agent_id, set()))

    def get_stats(self) -> Dict:
        return {
            "active_calls": len(self._active_calls),
            "agents_involved": len(self._agent_active_chains),
            "max_depth": self._max_depth,
            "max_concurrent": self._max_concurrent_chains,
        }
