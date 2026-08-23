"""TDD: logosai SDK 의 incoming traceparent header 처리.

Phase 4b — logos_api 가 보낸 W3C traceparent header 를 ACP 측이 받아서
            TraceSpan 의 ContextVar 에 set → 같은 trace_id 로 span 기록.

검증:
  parse_traceparent("00-{32hex}-{16hex}-01") → (trace_id_uuid, span_id)
  TraceSpanContext (context manager) → 진입 시 ContextVar set, 종료 시 reset
  새 span 이 inherited trace_id 사용
"""
import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class TestParseTraceparent(unittest.TestCase):

    def test_function_exists(self):
        from logosai.utils.trace_span import parse_traceparent
        self.assertTrue(callable(parse_traceparent))

    def test_valid_w3c_format(self):
        from logosai.utils.trace_span import parse_traceparent
        # 32 hex trace_id + 16 hex span_id
        tp = "00-aabbccddeeff00112233445566778899-aabbccddeeff0011-01"
        trace_id, parent_id = parse_traceparent(tp)
        self.assertIsNotNone(trace_id)
        self.assertIsNotNone(parent_id)
        # trace_id 가 UUID 형식으로 정규화 (8-4-4-4-12)
        self.assertEqual(len(trace_id), 36)
        # uuid4() 와 같은 형태로 파싱 가능해야 (또는 32 hex 그대로)
        self.assertEqual(trace_id.replace("-", "").lower(),
                         "aabbccddeeff00112233445566778899")
        self.assertEqual(parent_id, "aabbccddeeff0011")

    def test_returns_none_for_invalid(self):
        from logosai.utils.trace_span import parse_traceparent
        # 빈 / 잘못된 format
        self.assertEqual(parse_traceparent(""), (None, None))
        self.assertEqual(parse_traceparent(None), (None, None))
        self.assertEqual(parse_traceparent("invalid"), (None, None))
        self.assertEqual(parse_traceparent("00-tooshort-x-01"), (None, None))

    def test_handles_uuid_with_hyphens_in_trace(self):
        """우리 build_traceparent 가 padding 으로 짧은 hex 도 32 로 만드므로
        유효한 32hex 만 받으면 OK."""
        from logosai.utils.trace_span import parse_traceparent
        tp = "00-12345678123456781234567812345678-1234567812345678-01"
        trace_id, parent_id = parse_traceparent(tp)
        self.assertEqual(trace_id, "12345678-1234-5678-1234-567812345678")


class TestTraceContextManager(unittest.TestCase):

    def test_class_exists(self):
        from logosai.utils.trace_span import TraceContext
        self.assertTrue(callable(TraceContext))

    def test_sets_and_resets_context(self):
        from logosai.utils.trace_span import (
            TraceContext, get_current_trace_id, get_current_span_id,
        )
        # 초기 상태
        self.assertIsNone(get_current_trace_id())

        with TraceContext(trace_id="11111111-2222-3333-4444-555555555555",
                          parent_id="abcdef0123456789"):
            self.assertEqual(get_current_trace_id(), "11111111-2222-3333-4444-555555555555")
            self.assertEqual(get_current_span_id(), "abcdef0123456789")

        # 종료 후 reset
        self.assertIsNone(get_current_trace_id())
        self.assertIsNone(get_current_span_id())

    def test_none_inputs_no_op(self):
        """None trace_id 면 ContextVar 변경 없음 (에러 방지)."""
        from logosai.utils.trace_span import (
            TraceContext, get_current_trace_id,
        )
        with TraceContext(trace_id=None, parent_id=None):
            self.assertIsNone(get_current_trace_id())


class TestSpanInheritsExternalTrace(unittest.TestCase):
    """parse_traceparent + TraceContext + TraceSpan.start 의 통합 동작."""

    def test_span_uses_external_trace_id(self):
        from logosai.utils.trace_span import (
            parse_traceparent, TraceContext, TraceSpan,
        )
        # logos_api 가 보낸 traceparent
        tp = "00-aabbccddeeff00112233445566778899-aabbccddeeff0011-01"
        trace_id, parent_id = parse_traceparent(tp)

        with TraceContext(trace_id=trace_id, parent_id=parent_id):
            span = TraceSpan.start(name="agent.process", agent_id="x")
            try:
                # span 이 external trace_id 를 이어받아야
                self.assertEqual(span.trace_id, trace_id)
                self.assertEqual(span.parent_id, parent_id)
            finally:
                span.end(success=True)

    def test_span_without_context_uses_own_uuid(self):
        """TraceContext 없이 span 만 시작하면 새 uuid (기존 동작 유지)."""
        from logosai.utils.trace_span import TraceSpan
        span = TraceSpan.start(name="standalone")
        try:
            self.assertEqual(len(span.trace_id), 36)  # uuid4 형식
        finally:
            span.end(success=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
