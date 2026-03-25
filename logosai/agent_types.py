"""
LogosAI agent-related type definitions
"""

import os
import json
import logging
from enum import Enum, auto
from typing import Any, Dict, Optional, List, ClassVar, Set, Union, TypeVar, Type
from dataclasses import dataclass, field
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator
from loguru import logger

_cached_agent_types = None

JSON = Union[Dict[str, Any], List[Any], str, int, float, bool, None]

def get_agent_types(config_path: str = None, json_data: JSON = None) -> Dict[str, Dict[str, Any]]:
    """Load agent information (with caching)

    Args:
        config_path (str, optional): Path to agents.json file. Defaults to None, in which case examples/configs/agents.json is used.
        json_data (JSON, optional): JSON data to pass directly. Must be in JSON format.
                                  Can contain single agent info or multiple agent info (with 'agents' key).

    Returns:
        Dict[str, Dict[str, Any]]: Dictionary of agent information keyed by agent ID
    """
    global _cached_agent_types
    
    # Process json_data first if provided
    if json_data is not None:
        try:
            if isinstance(json_data, str):
                config = json.loads(json_data)
            else:
                config = json_data

            # Extract agent information from json_data
            new_agents = {}
            if isinstance(config, dict):
                if 'agents' in config:
                    new_agents = {agent['agent_id']: agent for agent in config.get('agents', [])}
                elif 'agent_id' in config:
                    new_agents = {config['agent_id']: config}

            # Initialize with new data if cache is empty
            if _cached_agent_types is None:
                _cached_agent_types = new_agents
                return _cached_agent_types

            # Update cache with new data if cache exists
            _cached_agent_types.update(new_agents)
            return _cached_agent_types

        except Exception as e:
            logger.error(f"Error processing JSON data: {str(e)}")
            if _cached_agent_types is None:
                _cached_agent_types = {}

    # Use default path if cache is empty and config_path is not provided
    if _cached_agent_types is None:
        try:
            if config_path is None:
                package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                config_path = os.path.join(package_dir, "examples", "configs", "agents.json")

            # Load agent information from file
            if os.path.exists(config_path):
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    _cached_agent_types = {agent['agent_id']: agent for agent in config.get('agents', [])}
            else:
                logger.warning(f"Agent config file not found: {config_path}")
                _cached_agent_types = {}

        except Exception as e:
            logger.error(f"Error loading agent config file: {str(e)}")
            _cached_agent_types = {}
    
    return _cached_agent_types


class AgentType(str, Enum):
    """Agent type enumeration"""
    TASK_CLASSIFIER = "task_classifier"  # Task classification agent
    MANAGED_SOURCE = "managed_source"    # Managed source agent
    SELF_HOSTED = "self_hosted"         # Self-hosted agent
    LLM_INTEGRATION = "llm_integration"  # LLM integration agent
    UNKNOWN = "unknown"                 # Unknown type
    GENERAL = "general"                 # General conversational agent
    SEARCH = "search"                   # Search agent
    CUSTOM = "custom"                   # Custom agent

class AgentResponseType(str, Enum):
    """Agent response type enumeration."""
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    TEXT = "TEXT"
    HTML = "HTML"
    JSON = "JSON"

    @classmethod
    def from_string(cls, value: str) -> 'AgentResponseType':
        """Convert a string to AgentResponseType (case-insensitive).

        Args:
            value: String representation of the response type.

        Returns:
            Matching AgentResponseType member, defaults to TEXT.
        """
        if not isinstance(value, str):
            return cls.TEXT
        upper = value.upper()
        for member in cls:
            if member.value == upper or member.name == upper:
                return member
        # Handle lowercase legacy values (e.g. "success" from types.py)
        for member in cls:
            if member.value.lower() == value.lower():
                return member
        return cls.TEXT


class TaskType(str):
    """Task type enumeration"""
    _values: Set[str] = None
    
    def __new__(cls, value):
        if cls._values is None:
            agent_types = get_agent_types()
            cls._values = set(agent_types.keys()) | {'unknown'}
        if value not in cls._values:
            value = 'unknown'
        return super().__new__(cls, value)


class ClassificationResult(BaseModel):
    """Pydantic model for classification results"""
    task_type: str = Field(description="Type of task")
    confidence: float = Field(description="Confidence of classification result (0-1)", ge=0, le=1)
    reasoning: str = Field(description="Reasoning for task type selection")
    requires_analysis: bool = Field(description="Whether additional analysis is required")

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @field_validator('task_type', mode='before')
    @classmethod
    def validate_task_type(cls, v):
        if isinstance(v, str):
            v = v.lower()
            agent_types = get_agent_types()
            if v not in agent_types and v != 'unknown':
                return 'unknown'
            return v
        return 'unknown'


class AgentResponse:
    """Agent response class"""
    def __init__(self, type: AgentResponseType, content: Dict[str, Any], metadata: Dict[str, Any] = None, message: str = None):
        self.type = type
        self.content = content
        self.metadata = metadata or {}
        self.message = message or ""  # Response summary or main message

    def to_dict(self) -> Dict[str, Any]:
        """Convert response to dictionary"""
        return {
            "type": str(self.type),
            "content": self.content,
            "metadata": self.metadata,
            "message": self.message
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AgentResponse':
        """Create an AgentResponse from a dictionary.

        Args:
            data: Dictionary with 'type', 'content', and optional 'metadata'/'message'.

        Returns:
            AgentResponse instance.
        """
        return cls(
            type=AgentResponseType.from_string(data.get("type", "TEXT")),
            content=data.get("content", {}),
            metadata=data.get("metadata", {}),
            message=data.get("message", "")
        )

    @classmethod
    def error(cls, message: str, content: Dict[str, Any] = None) -> 'AgentResponse':
        """Create error response"""
        return cls(
            type=AgentResponseType.ERROR,
            content=content or {"error": message},
            metadata={"error_message": message},
            message=message
        )

    @classmethod
    def success(cls, message: str = "", content: Dict[str, Any] = None) -> 'AgentResponse':
        """Create success response"""
        return cls(
            type=AgentResponseType.SUCCESS,
            content=content or {"message": message},
            metadata={"success_message": message},
            message=message
        )


# ═══════════════════════════════════════════
# L3: Real-time Collaboration Types
# ═══════════════════════════════════════════

@dataclass
class Opinion:
    """Response from ask_opinion() — another agent's judgment."""
    agent_id: str
    agrees: bool
    confidence: float
    reasoning: str
    suggestion: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"agent_id": self.agent_id, "agrees": self.agrees,
                "confidence": self.confidence, "reasoning": self.reasoning,
                "suggestion": self.suggestion}


@dataclass
class HelpResult:
    """Response from request_help() — whether another agent can assist."""
    agent_id: str
    available: bool
    result: Any = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"agent_id": self.agent_id, "available": self.available,
                "result": self.result, "reason": self.reason}


@dataclass
class Acknowledgment:
    """Response from share_finding() — whether the agent received and will act."""
    agent_id: str
    received: bool
    will_act: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"agent_id": self.agent_id, "received": self.received,
                "will_act": self.will_act}


# ═══════════════════════════════════════════
# L4: Learning Sharing Types
# ═══════════════════════════════════════════

@dataclass
class Learning:
    """A learned pattern that can be shared between agents."""
    source_agent: str
    pattern: str
    solution: str
    confidence: float
    tags: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    usage_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"source_agent": self.source_agent, "pattern": self.pattern,
                "solution": self.solution, "confidence": self.confidence,
                "tags": self.tags, "timestamp": self.timestamp,
                "usage_count": self.usage_count}
