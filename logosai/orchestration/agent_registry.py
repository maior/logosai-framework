"""
Agent Registry

Central registry for all available agents with their metadata,
capabilities, and I/O schemas. Used by Query Planner to select
appropriate agents for task execution.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .models import AgentSchema, AgentRegistryEntry
from .exceptions import AgentNotFoundError

logger = logging.getLogger(__name__)


class AgentRegistry:
    """
    Central registry for managing agent metadata.

    Features:
    - Starts empty; an organization's default agents are injected (defaults=)
    - Dynamic agent registration/deregistration
    - Query by capability, tags, or agent ID
    - Build prompt context for Query Planner

    Example:
        registry = AgentRegistry(defaults=my_default_entries)  # 또는 AgentRegistry()
        registry.register_agent(entry)

        # Get all agents
        agents = registry.get_all_agents()

        # Get agent by ID
        agent = registry.get_agent("search_agent")

        # Get agents by capability
        search_agents = registry.get_agents_by_capability("web_search")

        # Build context for LLM prompt
        context = registry.build_prompt_context()
    """

    # Default agent definitions with comprehensive metadata
    #: 기본 에이전트 — SDK 는 비어 있다. 조직의 기본 목록은 생성자 defaults= 로 넣는다
    #: (Logos 목록: ontology.orchestrator.logos_agents, 2026-10-05 이전).
    DEFAULT_AGENTS: List[AgentRegistryEntry] = []

    def __init__(
        self,
        config_path: Optional[Path] = None,
        defaults: Optional[Iterable[AgentRegistryEntry]] = None,
    ):
        """
        Initialize the agent registry.

        Args:
            config_path: Optional path to agent configuration file
            defaults: 처음에 넣을 에이전트 (기본: DEFAULT_AGENTS, SDK 에선 비어 있음).
                등록 순서가 플래너 프롬프트의 나열 순서가 된다.
        """
        self._agents: Dict[str, AgentRegistryEntry] = {}
        self._defaults = list(self.DEFAULT_AGENTS if defaults is None else defaults)
        self._config_path = config_path
        self._initialized = False

    def initialize(self) -> None:
        """Initialize registry with default agents and config file if available"""
        if self._initialized:
            return

        # Load default agents
        for agent in self._defaults:
            self._agents[agent.agent_id] = agent

        # Load from config file if provided
        if self._config_path and self._config_path.exists():
            self._load_from_config(self._config_path)

        self._initialized = True
        logger.info(f"Agent registry initialized with {len(self._agents)} agents")

    def _load_from_config(self, config_path: Path) -> None:
        """Load additional agent configurations from JSON file"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)

            for agent_id, agent_data in config.items():
                if agent_id not in self._agents:
                    # Create new entry from config
                    entry = self._create_entry_from_config(agent_id, agent_data)
                    if entry:
                        self._agents[agent_id] = entry
                else:
                    # Update existing entry with config data
                    self._update_entry_from_config(agent_id, agent_data)

            logger.info(f"Loaded agent config from {config_path}")
        except Exception as e:
            logger.warning(f"Failed to load agent config from {config_path}: {e}")

    def _create_entry_from_config(
        self,
        agent_id: str,
        config: Dict[str, Any]
    ) -> Optional[AgentRegistryEntry]:
        """Create AgentRegistryEntry from config dictionary"""
        try:
            schema = AgentSchema(
                input_type=config.get("input_type", "query"),
                output_type=config.get("output_type", "text"),
            )
            return AgentRegistryEntry(
                agent_id=agent_id,
                name=config.get("name", agent_id),
                description=config.get("description", ""),
                capabilities=config.get("capabilities", []),
                tags=config.get("tags", []),
                schema=schema,
                display_name=config.get("display_name"),
                display_name_ko=config.get("display_name_ko"),
                icon=config.get("icon", "🤖"),
                color=config.get("color", "#6366f1"),
                priority=config.get("priority", 0),
            )
        except Exception as e:
            logger.warning(f"Failed to create agent entry for {agent_id}: {e}")
            return None

    def _update_entry_from_config(
        self,
        agent_id: str,
        config: Dict[str, Any]
    ) -> None:
        """Update existing agent entry with config data"""
        entry = self._agents[agent_id]

        # Update fields if present in config
        if "description" in config and config["description"]:
            entry.description = config["description"]
        if "capabilities" in config and config["capabilities"]:
            entry.capabilities = config["capabilities"]
        if "tags" in config and config["tags"]:
            entry.tags = config["tags"]

    def get_all_agents(self) -> List[AgentRegistryEntry]:
        """Get all registered agents"""
        if not self._initialized:
            self.initialize()
        return list(self._agents.values())

    def get_agent(self, agent_id: str) -> AgentRegistryEntry:
        """
        Get agent by ID.

        Raises:
            AgentNotFoundError: If agent is not found
        """
        if not self._initialized:
            self.initialize()

        if agent_id not in self._agents:
            raise AgentNotFoundError(
                agent_id=agent_id,
                available_agents=list(self._agents.keys())
            )
        return self._agents[agent_id]

    def get_agent_safe(self, agent_id: str) -> Optional[AgentRegistryEntry]:
        """Get agent by ID, returns None if not found"""
        if not self._initialized:
            self.initialize()
        return self._agents.get(agent_id)

    def has_agent(self, agent_id: str) -> bool:
        """Check if agent exists in registry"""
        if not self._initialized:
            self.initialize()
        return agent_id in self._agents

    def register_agent(self, entry: AgentRegistryEntry) -> None:
        """Register a new agent or update existing"""
        if not self._initialized:
            self.initialize()
        self._agents[entry.agent_id] = entry
        logger.info(f"Registered agent: {entry.agent_id}")

    def unregister_agent(self, agent_id: str) -> bool:
        """Unregister an agent. Returns True if agent was found and removed."""
        # 먼저 초기화한다 — 안 하면 첫 호출이 삭제일 때 아무것도 안 지우고,
        # 다음 조회가 기본 에이전트를 다시 채워 삭제가 조용히 되돌려진다.
        if not self._initialized:
            self.initialize()
        if agent_id in self._agents:
            del self._agents[agent_id]
            logger.info(f"Unregistered agent: {agent_id}")
            return True
        return False

    def get_agents_by_capability(self, capability: str) -> List[AgentRegistryEntry]:
        """Get all agents with a specific capability"""
        if not self._initialized:
            self.initialize()

        return [
            agent for agent in self._agents.values()
            if capability.lower() in [c.lower() for c in agent.capabilities]
        ]

    def get_agents_by_tag(self, tag: str) -> List[AgentRegistryEntry]:
        """Get all agents with a specific tag"""
        if not self._initialized:
            self.initialize()

        return [
            agent for agent in self._agents.values()
            if tag.lower() in [t.lower() for t in agent.tags]
        ]

    def get_available_agents(self) -> List[AgentRegistryEntry]:
        """Get all currently available agents (is_available=True)"""
        if not self._initialized:
            self.initialize()

        return [
            agent for agent in self._agents.values()
            if agent.is_available
        ]

    def get_agent_ids(self) -> List[str]:
        """Get list of all agent IDs"""
        if not self._initialized:
            self.initialize()
        return list(self._agents.keys())

    def build_prompt_context(self, include_schema: bool = False) -> str:
        """
        Build context string for Query Planner LLM prompt.

        This creates a formatted string describing all available agents
        that can be included in the planning prompt.

        Args:
            include_schema: Whether to include I/O schema details

        Returns:
            Formatted string describing available agents
        """
        if not self._initialized:
            self.initialize()

        agents = self.get_available_agents()
        lines = ["# 사용 가능한 에이전트 목록\n"]

        for agent in sorted(agents, key=lambda a: -a.priority):
            lines.append(f"## {agent.agent_id}")
            lines.append(f"- 이름: {agent.name}")
            lines.append(f"- 설명: {agent.description}")
            # Convert capabilities and tags to strings (handle dict objects)
            capabilities_str = ', '.join(
                c if isinstance(c, str) else (c.get('name', str(c)) if isinstance(c, dict) else str(c))
                for c in agent.capabilities
            ) if agent.capabilities else ''
            tags_str = ', '.join(
                t if isinstance(t, str) else (t.get('name', str(t)) if isinstance(t, dict) else str(t))
                for t in agent.tags
            ) if agent.tags else ''
            lines.append(f"- 능력: {capabilities_str}")
            lines.append(f"- 태그: {tags_str}")

            if include_schema:
                lines.append(f"- 입력 타입: {agent.schema.input_type}")
                lines.append(f"- 출력 타입: {agent.schema.output_type}")

            lines.append("")

        return "\n".join(lines)

    def build_agents_dict(self) -> Dict[str, Dict[str, Any]]:
        """
        Build dictionary of agents for JSON serialization.

        Returns:
            Dictionary with agent_id as key and agent details as value
        """
        if not self._initialized:
            self.initialize()

        return {
            agent.agent_id: agent.to_dict()
            for agent in self.get_available_agents()
        }

    def get_schema_compatibility(
        self,
        source_agent_id: str,
        target_agent_id: str
    ) -> bool:
        """
        Check if source agent's output is compatible with target agent's input.

        Returns:
            True if schemas are compatible (possibly with transformation)
        """
        source = self.get_agent_safe(source_agent_id)
        target = self.get_agent_safe(target_agent_id)

        if not source or not target:
            return False

        return source.schema.is_compatible_with(target.schema)

    def __bool__(self) -> bool:
        """레지스트리 객체는 비어 있어도 참이다.

        __len__ 만 있으면 빈 레지스트리가 거짓이 되어 `registry or get_registry()` 가
        호출자가 넘긴 빈 레지스트리를 버리고 전역을 쓴다 (logos_api 는 빈 레지스트리를
        넘긴 뒤 DB 로 채운다). 기본 에이전트가 늘 있던 동안 '있으면 참'이 사실상의
        계약이었다 (2026-10-05, 기본 목록을 SDK 에서 뺄 때 드러남).
        """
        return True

    def __len__(self) -> int:
        if not self._initialized:
            self.initialize()
        return len(self._agents)

    def __contains__(self, agent_id: str) -> bool:
        return self.has_agent(agent_id)

    def __iter__(self):
        if not self._initialized:
            self.initialize()
        return iter(self._agents.values())


# Singleton instance for global access
_default_registry: Optional[AgentRegistry] = None


def get_registry() -> AgentRegistry:
    """Get the default global agent registry"""
    global _default_registry
    if _default_registry is None:
        _default_registry = AgentRegistry()
        _default_registry.initialize()
    return _default_registry
