"""agents/base.py 정리 테스트.

수정 전: agents/base.py에 별도 LogosAIAgent 정의 (520줄, 구버전)
수정 후: agents/base.py가 agent.py의 LogosAIAgent를 re-export

테스트:
1. from logosai.agent import LogosAIAgent → 현재 버전
2. from logosai.agents.base import LogosAIAgent → 같은 클래스여야 함
3. from logosai import LogosAIAgent → 같은 클래스여야 함
4. agents/base.py의 create_agent도 정상 동작
5. SimpleAgent이 LogosAIAgent의 서브클래스
6. rag_agent_v2 import가 정상 동작
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestSingleClass:
    """모든 import 경로에서 같은 LogosAIAgent 클래스가 나와야 함."""

    def test_agent_py_import(self):
        from logosai.agent import LogosAIAgent
        assert LogosAIAgent is not None
        assert hasattr(LogosAIAgent, 'run_with_tools')  # Mixin 메서드
        assert hasattr(LogosAIAgent, 'react')
        assert hasattr(LogosAIAgent, 'call_agent')

    def test_agents_base_import(self):
        """agents/base.py에서 import해도 같은 클래스."""
        from logosai.agents.base import LogosAIAgent as BaseAgent
        from logosai.agent import LogosAIAgent as MainAgent
        assert BaseAgent is MainAgent, \
            f"agents/base.py의 LogosAIAgent({id(BaseAgent)})와 agent.py의 LogosAIAgent({id(MainAgent)})가 다른 클래스!"

    def test_top_level_import(self):
        """from logosai import LogosAIAgent도 같은 클래스."""
        from logosai import LogosAIAgent as TopAgent
        from logosai.agent import LogosAIAgent as MainAgent
        assert TopAgent is MainAgent

    def test_simple_agent_subclass(self):
        from logosai.simple_agent import SimpleAgent
        from logosai.agent import LogosAIAgent
        assert issubclass(SimpleAgent, LogosAIAgent)

    def test_has_mixin_methods(self):
        """agents/base.py에서 import한 클래스도 Mixin 메서드가 있어야 함."""
        from logosai.agents.base import LogosAIAgent
        assert hasattr(LogosAIAgent, 'register_tool')
        assert hasattr(LogosAIAgent, 'memorize')
        assert hasattr(LogosAIAgent, 'plan')


class TestCreateAgent:
    """agents/base.py의 create_agent도 정상 동작해야 함."""

    def test_create_agent_from_base(self):
        from logosai.agents.base import create_agent
        assert callable(create_agent)

    def test_create_agent_from_agent(self):
        from logosai.agent import create_agent
        assert callable(create_agent)

    def test_both_create_agent_same(self):
        from logosai.agents.base import create_agent as base_create
        from logosai.agent import create_agent as main_create
        assert base_create is main_create


class TestRagAgentCompat:
    """rag_agent_v2가 정상 import되는지."""

    def test_rag_agent_import(self):
        """examples/agents/rag_agent_v2.py의 import 경로가 동작."""
        from logosai.agents.base import LogosAIAgent
        from logosai.config import AgentConfig
        from logosai.agent_types import AgentType

        # RAGAgentV2가 사용하는 패턴 시뮬레이션
        config = AgentConfig(name="test_rag", agent_type=AgentType.CUSTOM)
        agent = LogosAIAgent(config)
        assert agent.name == "test_rag"
        assert hasattr(agent, 'run_with_tools')


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
