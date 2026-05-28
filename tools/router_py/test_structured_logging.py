#!/usr/bin/env python3
"""
Tests for structured_logging.py.

Run with:
    cd /home/mike/lucy-v10 && source ui-v10/.venv/bin/activate
    python3 -m pytest tools/router_py/test_structured_logging.py -v
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from router_py.structured_logging import (
    ContextualLogger,
    StructuredFormatter,
    clear_logger_cache,
    configure_logging,
    get_structured_logger,
)


@pytest.fixture(autouse=True)
def _clear_logger_cache():
    clear_logger_cache()
    yield
    clear_logger_cache()


# ---------------------------------------------------------------------------
# StructuredFormatter
# ---------------------------------------------------------------------------

class TestStructuredFormatter:
    def test_outputs_valid_json(self):
        fmt = StructuredFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        line = fmt.format(record)
        parsed = json.loads(line)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "hello"
        assert parsed["logger"] == "test"
        assert "timestamp" in parsed

    def test_includes_extra_fields(self):
        fmt = StructuredFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        record.request_id = "abc123"
        record.latency_ms = 42
        line = fmt.format(record)
        parsed = json.loads(line)
        assert parsed["request_id"] == "abc123"
        assert parsed["latency_ms"] == 42

    def test_exception_included(self):
        fmt = StructuredFormatter()
        try:
            raise ValueError("boom")
        except Exception:
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname="", lineno=0,
                msg="error", args=(), exc_info=sys.exc_info(),
            )
        line = fmt.format(record)
        parsed = json.loads(line)
        assert "exception" in parsed
        assert "boom" in parsed["exception"]

    def test_iso_timestamp(self):
        fmt = StructuredFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        line = fmt.format(record)
        parsed = json.loads(line)
        ts = parsed["timestamp"]
        assert "T" in ts
        assert ts.endswith("Z") or "+" in ts

    def test_non_serializable_fallback(self):
        fmt = StructuredFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        record.weird = object()  # type: ignore[attr-defined]
        line = fmt.format(record)
        parsed = json.loads(line)
        assert "<object" in parsed["weird"] or "unserializable" in parsed["weird"]


# ---------------------------------------------------------------------------
# configure_logging
# ---------------------------------------------------------------------------

class TestConfigureLogging:
    def test_sets_json_formatter(self):
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        configure_logging(level="INFO", handler=handler)
        logger = logging.getLogger("test_configure")
        logger.info("hello world")
        line = stream.getvalue().strip()
        parsed = json.loads(line)
        assert parsed["message"] == "hello world"
        assert parsed["level"] == "INFO"

    def test_idempotent(self):
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        configure_logging(level="INFO", handler=handler)
        configure_logging(level="DEBUG", handler=handler)
        root = logging.getLogger()
        assert len(root.handlers) == 1


# ---------------------------------------------------------------------------
# ContextualLogger
# ---------------------------------------------------------------------------

class TestContextualLogger:
    def test_bind_adds_fields(self):
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        configure_logging(level="INFO", handler=handler)
        logger = get_structured_logger("test_ctx").bind(request_id="r1")
        logger.info("msg")
        line = stream.getvalue().strip()
        parsed = json.loads(line)
        assert parsed["request_id"] == "r1"
        assert parsed["message"] == "msg"

    def test_bind_is_immutable(self):
        logger = get_structured_logger("test_immut")
        bound_a = logger.bind(a=1)
        bound_b = bound_a.bind(b=2)
        # bound_a should not have 'b'
        stream_a = StringIO()
        handler_a = logging.StreamHandler(stream_a)
        configure_logging(level="INFO", handler=handler_a)
        bound_a.info("a")
        parsed_a = json.loads(stream_a.getvalue().strip())
        assert "a" in parsed_a
        assert "b" not in parsed_a

    def test_unbind_removes_fields(self):
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        configure_logging(level="INFO", handler=handler)
        logger = get_structured_logger("test_unbind").bind(a=1, b=2)
        logger.unbind("a").info("msg")
        parsed = json.loads(stream.getvalue().strip())
        assert "a" not in parsed
        assert "b" in parsed

    def test_thread_safety(self):
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        configure_logging(level="INFO", handler=handler)
        results: list[dict] = []
        lock = threading.Lock()

        def worker(tid: int):
            logger = get_structured_logger("test_thread").bind(thread_id=tid)
            logger.info(f"from {tid}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        lines = [l for l in stream.getvalue().strip().split("\n") if l]
        assert len(lines) == 10
        thread_ids = set()
        for line in lines:
            parsed = json.loads(line)
            thread_ids.add(parsed["thread_id"])
        assert len(thread_ids) == 10

    def test_level_methods(self):
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        configure_logging(level="DEBUG", handler=handler)
        logger = get_structured_logger("test_levels")
        logger.debug("d")
        logger.info("i")
        logger.warning("w")
        logger.error("e")
        logger.critical("c")
        lines = [l for l in stream.getvalue().strip().split("\n") if l]
        assert len(lines) == 5
        levels = [json.loads(l)["level"] for l in lines]
        assert levels == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    def test_exception_method(self):
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        configure_logging(level="INFO", handler=handler)
        logger = get_structured_logger("test_exc")
        try:
            raise RuntimeError("fail")
        except Exception:
            logger.exception("oops")
        parsed = json.loads(stream.getvalue().strip())
        assert parsed["level"] == "ERROR"
        assert "exception" in parsed
        assert "fail" in parsed["exception"]

    def test_extra_merge(self):
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        configure_logging(level="INFO", handler=handler)
        logger = get_structured_logger("test_extra").bind(a=1)
        logger.info("msg", extra={"b": 2})
        parsed = json.loads(stream.getvalue().strip())
        assert parsed["a"] == 1
        assert parsed["b"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
