"""공개 저장소에 접속 정보·키를 두지 않는다 (2026-10-09).

사고: 통합 테스트 2개에 내부 DB 주소와 비밀번호가 평문으로 있었고 공개 main 에 올라가
있었다. 같은 비밀번호가 logosai-pulse 의 설정 기본값에도 있었다. 이 저장소는 공개다 —
접속 정보는 환경변수(LOGOSAI_TEST_DB_URL 등)로만 받는다.

계약: git 추적 파일 어디에도 계정이 든 DB 주소나 알려진 키 형태가 없다.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 꺾쇠 자리표시(<password>)와 ${VAR} 치환은 비밀이 아니다 — 문자 집합에서 뺀다
CRED_URL = re.compile(r"postgres(?:ql)?(?:\+asyncpg)?://[^\s:'\"/@{}<>$]+:[^\s@'\"{}<>$]+@(?!localhost[:/])[^\s'\"]+")
KEY_SHAPES = re.compile(r"AIza[0-9A-Za-z_\-]{30,}|sk-(?:proj-)?[A-Za-z0-9]{32,}|sk-ant-[A-Za-z0-9_\-]{30,}|ghp_[A-Za-z0-9]{30,}")
SKIP_SUFFIX = (".png", ".jpg", ".ico", ".gif", ".woff", ".woff2", ".pdf", ".whl", ".gz")


def test_checker_catches_what_it_should():
    """대조군 — 검사식이 실제 형태를 잡는다. 시험 문자열은 실행 중에 조립한다
    (소스에 그대로 적으면 아래 전수 검사가 이 파일을 건다)."""
    assert CRED_URL.search("postgresql://" + "u" + ":" + "secret9" + "@" + "10.1.2.3:5432/db")
    assert not CRED_URL.search("postgresql://x:x@localhost:5432/x")
    assert not CRED_URL.search("postgresql://<user>:<password>@<host>:5432/<db>")
    assert not CRED_URL.search("postgresql+asyncpg://postgres:${POSTGRES_PASSWORD}@postgres:5432/x")
    assert KEY_SHAPES.search("AIza" + "B" * 35)


def test_no_tracked_file_contains_credentials_or_keys():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert len(files) > 100                              # 대조군 — 실제로 훑었다
    bad = []
    for f in files:
        p = ROOT / f
        if p.suffix in SKIP_SUFFIX or not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        if CRED_URL.search(text) or KEY_SHAPES.search(text):
            bad.append(f)
    assert bad == [], f"접속 정보·키가 든 추적 파일: {bad}"
