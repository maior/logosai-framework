"""StandardExportMixin — 에이전트를 MCP tool / A2A skill 표준 스키마로 self-describe.

ACP 없이 SDK 단독(SimpleACPServer 등)으로 배포할 때도 표준 노출을 가능하게 한다.
ACP 경로의 schema_mapper와 동일한 규칙을 에이전트 인스턴스 레벨로 옮긴 것 —
원천은 self.config(name/description/agent_id) + self._tools(ToolUseMixin 등록분).
"""

import re
from typing import Any, Dict, List

# agents.json parameters 안의 LLM 실행 설정 키 (사용자 입력 아님 → inputSchema 제외)
_LLM_CONFIG_KEYS = {"model", "temperature", "max_tokens"}
_NAME_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9_-]")


class StandardExportMixin:
    """MCP/A2A 표준 스키마 파생 메서드. LogosAIAgent에 믹스인."""

    def _std_agent_id(self) -> str:
        return (getattr(self.config, "agent_id", None)
                or getattr(self.config, "name", None)
                or self.__class__.__name__)

    def _std_description(self) -> str:
        return getattr(self.config, "description", "") or self._std_agent_id()

    def _std_mcp_name(self) -> str:
        """MCP 도구 이름 규칙 [a-zA-Z0-9_-]{1,128} 로 sanitize (한글 이름 등 대응)."""
        name = _NAME_SANITIZE_RE.sub("_", self._std_agent_id()).strip("_")[:128]
        return name or "agent"

    def _std_tags(self) -> List[str]:
        cfg = getattr(self.config, "config", {}) or {}
        tags = [t for t in cfg.get("tags", []) if isinstance(t, str)]
        for tool in getattr(self, "_tools", []):
            name = tool.get("name")
            if isinstance(name, str) and name not in tags:
                tags.append(name)
        return tags

    def _std_examples(self) -> List[str]:
        cfg = getattr(self.config, "config", {}) or {}
        return [e for e in cfg.get("examples", []) if isinstance(e, str)][:3]

    def to_mcp_tool(self) -> Dict[str, Any]:
        """이 에이전트를 MCP tool 정의로 변환 {name, description, inputSchema}.

        도구(self._tools)의 파라미터가 있으면 inputSchema.properties로 승격,
        query는 항상 존재+필수(자연어 진입 보장). name은 MCP 규칙으로 sanitize.
        """
        properties: Dict[str, Any] = {"query": {"type": "string", "description": "자연어 요청"}}
        required: List[str] = ["query"]

        for tool in getattr(self, "_tools", []):
            for key, prop in (tool.get("parameters") or {}).items():
                if key in _LLM_CONFIG_KEYS or key == "query" or not isinstance(prop, dict):
                    continue
                # ToolUseMixin flat 파라미터 → JSON Schema 프로퍼티 (required 플래그 분리)
                schema_prop = {k: v for k, v in prop.items() if k != "required"}
                schema_prop.setdefault("type", "string")
                properties[key] = schema_prop
                if prop.get("required") is True and key not in required:
                    required.append(key)

        return {
            "name": self._std_mcp_name(),
            "description": self._std_description(),
            "inputSchema": {"type": "object", "properties": properties, "required": required},
        }

    def to_a2a_skill(self) -> Dict[str, Any]:
        """이 에이전트를 A2A AgentCard skill로 변환.

        {id, name, description, tags, examples, inputModes, outputModes}.
        tags = config.config['tags'] + 등록 도구 이름.
        """
        return {
            "id": self._std_agent_id(),
            "name": getattr(self.config, "name", self._std_agent_id()),
            "description": self._std_description(),
            "tags": self._std_tags(),
            "examples": self._std_examples(),
            "inputModes": ["text/plain"],
            "outputModes": ["text/plain", "application/json"],
        }
