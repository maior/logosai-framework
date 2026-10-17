"""Claude Code 플러그인(logosai-acp) 계약 — 설치되는 것이 실제로 브리지를 가리키는가.

플러그인은 `logosai mcp` 브리지를 Claude Code 에 자동 등록하는 포장이다. 파일은 JSON 과
마크다운뿐이라 깨져도 파이썬 테스트가 모른다 — 그래서 구조를 여기서 고정한다.
최종 확인은 `claude plugin validate <dir> --strict` (CLI 가 있을 때만).
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "integrations" / "claude-code" / "logosai-acp"
MARKET = ROOT / ".claude-plugin" / "marketplace.json"


def _json(p):
    return json.loads(p.read_text(encoding="utf-8"))


def test_manifest_and_user_config():
    m = _json(PLUGIN / ".claude-plugin" / "plugin.json")
    assert m["name"] == "logosai-acp" and re.fullmatch(r"[a-z0-9-]+", m["name"])
    uc = m["userConfig"]
    assert {"logosai_bin", "acp_url", "agents"} <= set(uc)
    assert uc["agents"].get("required") is True          # 허용 목록 없이 설치되지 않는다


def test_mcp_server_launches_the_bridge_with_user_values():
    srv = _json(PLUGIN / ".mcp.json")["mcpServers"]["logosai"]
    m = _json(PLUGIN / ".claude-plugin" / "plugin.json")
    refs = set(re.findall(r"\$\{user_config\.([a-z_]+)\}", json.dumps(srv)))
    assert refs <= set(m["userConfig"])                    # 정의되지 않은 값을 참조하지 않는다
    assert srv["command"] == "${user_config.logosai_bin}"
    args = srv["args"]
    assert args[0] == "mcp" and "--acp" in args and "--agents" in args
    assert "LOGOSAI_ACP_TOKEN" not in json.dumps(args)     # 토큰은 인자로 넘기지 않는다


def test_marketplace_points_at_the_plugin():
    mk = _json(MARKET)
    entry = next(p for p in mk["plugins"] if p["name"] == "logosai-acp")
    assert (ROOT / entry["source"]).resolve() == PLUGIN.resolve()


def test_commands_and_skill_reference_the_bridge_tools():
    text = "".join(p.read_text(encoding="utf-8") for p in (PLUGIN / "commands").glob("*.md"))
    text += (PLUGIN / "skills" / "logosai-acp" / "SKILL.md").read_text(encoding="utf-8")
    assert "logosai_ask" in text and "logosai_agents" in text


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI 없음")
def test_claude_plugin_validate_strict():
    for target in (PLUGIN, ROOT):
        p = subprocess.run(["claude", "plugin", "validate", str(target), "--strict"],
                           capture_output=True, text=True, timeout=120)
        assert p.returncode == 0, p.stdout + p.stderr
