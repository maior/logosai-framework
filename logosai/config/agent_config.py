"""
Agent Configuration Management Module

This module provides classes and utilities for managing LogosAI agent configurations.
"""

from typing import Dict, Any, Optional, List, Union
from ..agent_types import AgentType


class AgentConfig:
    """Agent Configuration Class

    Class for managing LogosAI agent configurations.
    """
    
    def __init__(
        self,
        name: str,
        agent_type: Union[AgentType, str],
        description: str = "",
        config: Optional[Dict[str, Any]] = None,
        api_config: Optional[Dict[str, Any]] = None,
        llm_config: Optional[Dict[str, Any]] = None
    ):
        """Initialize agent configuration

        Args:
            name: Agent name
            agent_type: Agent type
            description: Agent description
            config: General agent configuration
            api_config: API connection settings
            llm_config: LLM model settings
        """
        self.name = name

        # Set agent type
        if isinstance(agent_type, str):
            # Convert string to AgentType enum
            try:
                self.agent_type = AgentType(agent_type)
            except ValueError:
                self.agent_type = AgentType.UNKNOWN
        else:
            self.agent_type = agent_type
        
        self.description = description
        self.config = config or {}
        self.api_config = api_config or {}
        self.llm_config = llm_config or {}
    
    def update(self, **kwargs) -> 'AgentConfig':
        """Update configuration

        Updates configuration with values passed as keyword arguments.

        Returns:
            Updated configuration object (self)
        """
        for key, value in kwargs.items():
            if key == 'name':
                self.name = value
            elif key == 'agent_type':
                if isinstance(value, str):
                    try:
                        self.agent_type = AgentType(value)
                    except ValueError:
                        self.agent_type = AgentType.UNKNOWN
                else:
                    self.agent_type = value
            elif key == 'description':
                self.description = value
            elif key == 'config':
                self.config.update(value)
            elif key == 'api_config':
                self.api_config.update(value)
            elif key == 'llm_config':
                self.llm_config.update(value)
        
        return self
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary

        Returns:
            Dictionary containing configuration values
        """
        return {
            "name": self.name,
            "agent_type": str(self.agent_type),
            "description": self.description,
            "config": self.config.copy(),
            "api_config": self.api_config.copy(),
            "llm_config": self.llm_config.copy()
        }
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'AgentConfig':
        """Create configuration object from dictionary

        Args:
            config_dict: Dictionary containing configuration values

        Returns:
            Created AgentConfig object
        """
        return cls(
            name=config_dict.get("name", "Unknown Agent"),
            agent_type=config_dict.get("agent_type", AgentType.UNKNOWN),
            description=config_dict.get("description", ""),
            config=config_dict.get("config", {}),
            api_config=config_dict.get("api_config", {}),
            llm_config=config_dict.get("llm_config", {})
        )
    
    def __str__(self) -> str:
        """Return string representation"""
        return f"AgentConfig(name='{self.name}', type={self.agent_type})"

    def __repr__(self) -> str:
        """Return developer representation"""
        return (f"AgentConfig(name='{self.name}', type={self.agent_type}, "
                f"description='{self.description[:20]}...' if len(self.description) > 20 else self.description)") 