"""tests/ 공용 pytest 설정 (2026-11-10).

`live` 마커 — 실행 중인 서버·데이터베이스·진짜 API 키가 필요한 테스트.
기본 실행에서는 건너뛰고 `LOGOSAI_LIVE_TESTS=1` 일 때만 돈다.

예전에는 "키가 환경에 있으면 돈다"(skipif) 였다. 그러면 키를 가진 개발 기기에서는
`pytest tests` 한 번마다 진짜 LLM 이 호출돼 돈이 나가고, 결과가 네트워크에 달린다.
돌릴지는 키의 유무가 아니라 돌리는 사람이 정한다.
"""
import os

import pytest

_LIVE_ENV = "LOGOSAI_LIVE_TESTS"


def pytest_collection_modifyitems(config, items):
    if os.environ.get(_LIVE_ENV) == "1":
        return
    skip_live = pytest.mark.skip(reason=f"live 테스트 — {_LIVE_ENV}=1 로 실행")
    for item in items:
        if item.get_closest_marker("live") is not None:
            item.add_marker(skip_live)
