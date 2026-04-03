"""Approval System — Human-in-the-Loop for agent actions.

Enables agents to request user confirmation before risky actions
(email, messaging, file operations, etc.)

Usage:
    # In agent code:
    approved = await self.request_approval(
        action="send_email",
        description="Send report to maiordba@gmail.com",
        details={"to": "maiordba@gmail.com", "subject": "Report", "preview": "..."},
    )
    if approved:
        await self._send_email(...)
    else:
        return "사용자가 취소했습니다"

    # Decorator for auto-approval:
    @requires_approval(action="send_message")
    async def _send_message(self, recipient, message):
        ...
"""

import asyncio
import functools
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from loguru import logger


class InteractionType(Enum):
    """Types of user interaction requests."""
    APPROVAL = "approval"           # Yes/No confirmation
    CHOICE = "choice"               # Select from options
    INPUT = "input"                 # Free text input
    CANCEL = "cancel"               # Cancel running operation


class ApprovalStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class InteractionRequest:
    """A request for user interaction (approval, choice, input)."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    type: InteractionType = InteractionType.APPROVAL
    action: str = ""                # e.g., "send_email", "send_kakaotalk"
    description: str = ""           # Human-readable description
    details: Dict[str, Any] = field(default_factory=dict)  # Preview data
    options: List[str] = field(default_factory=list)        # For CHOICE type
    timeout_seconds: int = 30
    status: ApprovalStatus = ApprovalStatus.PENDING
    response: Optional[Any] = None  # User's response
    created_at: float = field(default_factory=time.time)
    agent_id: str = ""
    query: str = ""

    def to_sse_event(self) -> dict:
        """Convert to SSE event format for frontend."""
        return {
            "type": f"{self.type.value}_required",
            "data": {
                "request_id": self.id,
                "action": self.action,
                "description": self.description,
                "details": self.details,
                "options": self.options,
                "timeout": self.timeout_seconds,
                "agent_id": self.agent_id,
            },
            "timestamp": self.created_at,
        }


class ApprovalManager:
    """Manages pending approval requests with async wait/notify.

    Singleton — shared across all agents in the process.
    """

    _instance = None

    @classmethod
    def get(cls) -> 'ApprovalManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._pending: Dict[str, InteractionRequest] = {}
        self._events: Dict[str, asyncio.Event] = {}

    async def request(self, interaction: InteractionRequest) -> InteractionRequest:
        """Submit an interaction request and wait for user response.

        Returns the request with status and response filled in.
        Blocks until user responds or timeout.
        """
        self._pending[interaction.id] = interaction
        self._events[interaction.id] = asyncio.Event()

        logger.info(f"Approval requested: [{interaction.action}] {interaction.description[:50]}")

        try:
            await asyncio.wait_for(
                self._events[interaction.id].wait(),
                timeout=interaction.timeout_seconds,
            )
        except asyncio.TimeoutError:
            interaction.status = ApprovalStatus.TIMEOUT
            logger.info(f"Approval timeout: {interaction.id}")
        finally:
            self._events.pop(interaction.id, None)
            self._pending.pop(interaction.id, None)

        return interaction

    def respond(self, request_id: str, approved: bool, response: Any = None) -> bool:
        """Submit user's response to a pending request.

        Called by REST endpoint when user clicks approve/reject.
        Returns True if request was found and responded to.
        """
        interaction = self._pending.get(request_id)
        if not interaction:
            logger.warning(f"Approval response for unknown request: {request_id}")
            return False

        # Prevent double-response: only accept if still pending
        if interaction.status != ApprovalStatus.PENDING:
            logger.warning(f"Approval already resolved ({interaction.status.value}): {request_id}")
            return False

        interaction.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        interaction.response = response

        event = self._events.get(request_id)
        if event:
            event.set()  # Unblock the waiting agent

        logger.info(f"Approval {'approved' if approved else 'rejected'}: {request_id}")
        return True

    def cancel(self, request_id: str) -> bool:
        """Cancel a pending request."""
        interaction = self._pending.get(request_id)
        if not interaction:
            return False
        interaction.status = ApprovalStatus.CANCELLED
        event = self._events.get(request_id)
        if event:
            event.set()
        return True

    def get_pending(self) -> List[InteractionRequest]:
        """Get all pending requests."""
        return list(self._pending.values())


def requires_approval(action: str, description: str = ""):
    """Decorator: require user approval before executing this method.

    The decorated method must be on a LogosAIAgent (or subclass) that has
    request_approval() available.

    Usage:
        @requires_approval(action="send_email", description="Send email")
        async def _send_email(self, to, subject, body):
            ...

    If user rejects, the method returns {"approved": False, "reason": "rejected"}.
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            # Build details from args
            details = {}
            if args:
                details["args"] = [str(a)[:100] for a in args]
            if kwargs:
                details.update({k: str(v)[:100] for k, v in kwargs.items()})

            desc = description or f"{action}: {func.__name__}"

            # Request approval
            if hasattr(self, 'request_approval'):
                approved = await self.request_approval(
                    action=action,
                    description=desc,
                    details=details,
                )
                if not approved:
                    return {"approved": False, "reason": "User rejected"}

            return await func(self, *args, **kwargs)
        return wrapper
    return decorator
