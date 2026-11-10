"""LLMClient 온-프렘 OpenAI-호환 base_url 테스트 (2026-07-07).

사용자 요구: 온-프렘에서도 사용. vLLM/LMStudio/Ollama(/v1)/TGI/LocalAI 등은
OpenAI-호환 API 를 노출하므로, openai 프로바이더 + config-driven base_url 로
langchain 없이 온-프렘 서버를 가리킨다. 계약:
  - base_url 은 config(~/.logosai/config.json llm.base_url)/env
    (LOGOSAI_LLM_BASE_URL)에서 결정. 명시 인자 우선.
  - base_url 미설정 시 None(기존 클라우드 동작 불변).
  - base_url 설정 + provider=openai + api_key 없음 → 온-프렘 placeholder 키
    (AsyncOpenAI 가 None 키로 실패하지 않도록).
  - base_url 설정 시 initialize()가 langchain(ChatOpenAI) 건너뜀 → 온-프렘은
    langchain 불필요(네이티브 AsyncOpenAI 경로).
  - _call_openai 직접 경로가 base_url 로 AsyncOpenAI 생성.

두 가지로 돈다 (2026-11-10):
  - pytest: 검사 하나 = `test_*` 하나. 예전엔 `main()` 하나뿐이라 pytest 가 0건을 수집했다.
  - 직접 실행: python tests/test_llm_onprem_base_url.py  → 마지막 줄 `RESULT: GREEN`

예전 `main()` 은 LOGOSAI_LLM_PROVIDER / _MODEL / _BASE_URL 을 os.environ 에서
**지우고 되돌리지 않았다** — 사용자가 세워 둔 값이 있었다면 그 프로세스에서 사라졌다.
이제 환경은 monkeypatch/ScriptPatch 로만 바꾸고, 끝나면 되돌린 뒤 llm_defaults 캐시를
다시 읽힌다(`_teardown`).
"""
import os
import sys

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__":      # 스크립트 모드에서만 — pytest 는 pyproject 의 pythonpath 를 쓴다
    sys.path.insert(0, _PKG)

from _script_runner import block_pulse, run, run_tests, use_fake_api_keys  # noqa: E402

_ONPREM = "http://onprem.local:8000/v1"


def _defaults():
    from logosai.config import llm_defaults
    return llm_defaults


def _client(**kw):
    from logosai.utils.llm_client import LLMClient
    return LLMClient(provider="openai", **kw)


def _setup(mp):
    block_pulse(mp)
    use_fake_api_keys(mp)
    for k in ("LOGOSAI_LLM_PROVIDER", "LOGOSAI_LLM_MODEL", "LOGOSAI_LLM_BASE_URL"):
        mp.delenv(k, raising=False)
    _defaults().reload_config()


def _teardown():
    # 환경이 되돌려진 뒤에 불린다 — llm_defaults 의 캐시를 진짜 환경으로 되돌린다.
    _defaults().reload_config()


def _use_onprem(mp):
    mp.setenv("LOGOSAI_LLM_BASE_URL", _ONPREM)
    _defaults().reload_config()


def test_ob1_no_base_url_means_none():
    """OB-1 base_url 미설정 → None(기존 동작 불변)"""
    # 대조군: 속성이 실제로 있고, 값을 주면 그 값이 나온다 (None 이 '속성 없음'이 아님).
    assert _client(base_url="http://control:1/v1").base_url == "http://control:1/v1"
    assert getattr(_client(), "base_url", "x") is None


def test_ob2_env_base_url_is_applied(monkeypatch):
    """OB-2 env base_url 반영"""
    _use_onprem(monkeypatch)
    assert _client().base_url == _ONPREM


def test_ob3_base_url_without_key_gets_placeholder(monkeypatch):
    """OB-3 base_url 설정 + 키 없음 → placeholder(None 아님)"""
    # 환경에 진짜 OPENAI_API_KEY 가 있으면 그 키가 잡혀 placeholder 경로를 타지 않는다.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # 대조군: base_url 이 없으면 키도 없다 — placeholder 는 base_url 때문에 생긴다.
    assert not _client(api_key=None).api_key
    _use_onprem(monkeypatch)
    assert bool(_client(api_key=None).api_key)


def test_ob4_base_url_makes_initialize_skip_langchain(monkeypatch):
    """OB-4 base_url 설정 → initialize langchain 건너뜀(온-프렘 네이티브)"""
    _use_onprem(monkeypatch)
    c3 = _client()
    run(c3.initialize())        # 예외가 나면 그대로 실패 (예전엔 잡아서 False 로 바꿨다)
    assert c3._langchain_client is None
    # 대조군: 초기화가 실제로 일어났다 (아무것도 안 해도 _langchain_client 는 None 이다).
    assert c3._client is not None


def test_ob5_base_url_creates_native_async_openai_client(monkeypatch):
    """OB-5 base_url 설정 → 네이티브 AsyncOpenAI 클라이언트 생성"""
    _use_onprem(monkeypatch)
    c3 = _client()
    run(c3.initialize())
    assert c3._client is not None
    assert "onprem.local" in str(getattr(c3._client, "base_url", ""))


def test_ob6_explicit_base_url_argument_wins(monkeypatch):
    """OB-6 명시적 base_url 인자 우선"""
    assert _client(base_url="http://explicit:9000/v1").base_url == "http://explicit:9000/v1"
    # env 가 있어도 인자가 이긴다.
    _use_onprem(monkeypatch)
    assert _client(base_url="http://explicit:9000/v1").base_url == "http://explicit:9000/v1"


def test_ob7_removing_env_returns_to_none(monkeypatch):
    """OB-7 base_url 없음 → base_url None(클라우드 회귀)"""
    _use_onprem(monkeypatch)
    assert _client().base_url == _ONPREM       # 대조군: 세웠을 때는 보인다
    monkeypatch.delenv("LOGOSAI_LLM_BASE_URL")
    _defaults().reload_config()
    assert _client().base_url is None


# ══ pytest 배선 ═══════════════════════════════════════════════════════════

if "pytest" in sys.modules:
    import pytest

    @pytest.fixture(autouse=True)
    def _env(monkeypatch):
        _setup(monkeypatch)
        yield
        monkeypatch.undo()
        _teardown()


def main():
    return run_tests(globals(), setup=_setup, teardown=_teardown)


if __name__ == "__main__":
    sys.exit(main())
