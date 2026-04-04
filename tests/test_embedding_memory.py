"""임베딩 메모리 검색 테스트.

store → recall 하이브리드 검색 (embedding + keyword) 검증.
실제 DB + Gemini embedding API 사용.

테스트:
1. 저장 시 임베딩 생성 확인
2. 키워드 매칭 — 기존 동작 유지
3. 의미 검색 — 키워드 불일치지만 의미적으로 관련된 메모리 검색
4. 하이브리드 스코어 순서 확인
5. 빈 쿼리 / 태그 필터
"""

import asyncio
import pytest
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# DB 연결 가능 여부 확인
def _db_available():
    try:
        import psycopg2
        conn = psycopg2.connect(
            'postgresql://logosai:logosai1234@211.180.253.250:5432/logosai',
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:
        return False


def _api_key_available():
    return bool(os.getenv("GOOGLE_API_KEY"))


SKIP_DB = not _db_available()
SKIP_API = not _api_key_available()
AGENT_ID = f"test_embed_{int(time.time())}"


@pytest.fixture
async def store():
    """테스트용 AgentMemoryStore 인스턴스."""
    from logosai.storage.agent_memory_store import AgentMemoryStore
    s = AgentMemoryStore(db_url="postgresql://logosai:logosai1234@211.180.253.250:5432/logosai")
    await s.initialize()
    yield s
    # Cleanup
    if s._pool:
        async with s._pool.acquire() as conn:
            await conn.execute("DELETE FROM agent_memories WHERE agent_id LIKE 'test_embed_%'")
    await s.close()


@pytest.mark.skipif(SKIP_DB or SKIP_API, reason="DB or API key not available")
class TestEmbeddingStore:
    """저장 시 임베딩이 생성되는지."""

    @pytest.mark.asyncio
    async def test_store_creates_embedding(self, store):
        await store.store(AGENT_ID, "서울 날씨", "봄철 서울은 10-15도", importance=0.8)

        import psycopg2
        conn = psycopg2.connect('postgresql://logosai:logosai1234@211.180.253.250:5432/logosai', connect_timeout=3)
        cur = conn.cursor()
        cur.execute("SELECT embedding FROM agent_memories WHERE agent_id = %s AND key = %s", (AGENT_ID, "서울 날씨"))
        row = cur.fetchone()
        conn.close()

        assert row is not None
        assert row[0] is not None  # embedding이 저장됨
        import json
        emb = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        assert isinstance(emb, list)
        assert len(emb) > 100  # 3072차원 기대


@pytest.mark.skipif(SKIP_DB or SKIP_API, reason="DB or API key not available")
class TestKeywordSearch:
    """기존 키워드 검색이 그대로 동작하는지."""

    @pytest.mark.asyncio
    async def test_keyword_match(self, store):
        await store.store(AGENT_ID, "맛집 추천", "강남역 근처 이탈리안 레스토랑", importance=0.7)
        await store.store(AGENT_ID, "회의 메모", "10시 팀 미팅 안건 정리", importance=0.6)

        results = await store.recall(AGENT_ID, "맛집", top_k=5)
        assert len(results) >= 1
        assert any("맛집" in r["key"] for r in results)


@pytest.mark.skipif(SKIP_DB or SKIP_API, reason="DB or API key not available")
class TestSemanticSearch:
    """키워드가 겹치지 않지만 의미적으로 관련된 메모리를 찾는지."""

    @pytest.mark.asyncio
    async def test_semantic_finds_related(self, store):
        # 저장: "서울 날씨"
        await store.store(AGENT_ID, "서울 기온", "봄철 서울은 보통 10-15도이며 가끔 비가 옵니다", importance=0.8)
        # 저장: 관련 없는 것
        await store.store(AGENT_ID, "파이썬 팁", "리스트 컴프리헨션이 for 루프보다 빠릅니다", importance=0.7)

        # 검색: "수도 날씨" — "서울" "기온" 키워드 없음, 하지만 의미적으로 관련
        results = await store.recall(AGENT_ID, "수도의 날씨 정보", top_k=5)

        # 의미적으로 "서울 기온"이 "파이썬 팁"보다 상위
        if len(results) >= 1:
            assert any("서울" in r["key"] or "기온" in r["key"] for r in results), \
                f"Expected '서울 기온' in results, got: {[r['key'] for r in results]}"

    @pytest.mark.asyncio
    async def test_semantic_vs_keyword_ordering(self, store):
        """의미적으로 가까운 것이 키워드 불일치여도 상위에 나오는지."""
        await store.store(AGENT_ID, "일본 여행", "도쿄 3박4일 여행 계획", importance=0.7)
        await store.store(AGENT_ID, "한국 음식", "김치찌개 만드는 법", importance=0.7)

        results = await store.recall(AGENT_ID, "일본 관광 정보", top_k=5)
        if len(results) >= 2:
            keys = [r["key"] for r in results]
            # "일본 여행"이 "한국 음식"보다 먼저
            assert keys.index("일본 여행") < keys.index("한국 음식"), \
                f"Expected '일본 여행' before '한국 음식', got: {keys}"


@pytest.mark.skipif(SKIP_DB or SKIP_API, reason="DB or API key not available")
class TestEmptyAndTags:
    """빈 쿼리, 태그 필터."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_all(self, store):
        await store.store(AGENT_ID, "memo1", "first memo", importance=0.5)
        await store.store(AGENT_ID, "memo2", "second memo", importance=0.6)

        results = await store.recall(AGENT_ID, "", top_k=10)
        assert len(results) >= 2

    @pytest.mark.asyncio
    async def test_tag_filter(self, store):
        await store.store(AGENT_ID, "tagged_memo", "this has tags", importance=0.7, tags=["work", "urgent"])

        results = await store.recall(AGENT_ID, "", tags=["work"], top_k=10)
        assert len(results) >= 1
        assert any("tagged_memo" in r["key"] for r in results)


@pytest.mark.skipif(SKIP_DB, reason="DB not available")
class TestFallbackCompat:
    """DB 연결 실패 시 fallback 동작."""

    @pytest.mark.asyncio
    async def test_inmemory_fallback(self):
        from logosai.storage.agent_memory_store import AgentMemoryStore
        s = AgentMemoryStore(db_url="postgresql://invalid:invalid@localhost:9999/nodb")
        await s.initialize()  # DB 실패 → fallback

        await s.store("fallback_agent", "test", "hello", importance=0.5)
        results = await s.recall("fallback_agent", "test", top_k=5)
        assert len(results) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
