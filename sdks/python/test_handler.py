import logging
import time
import urllib.request
import urllib.error
from unittest.mock import patch, MagicMock
import pytest
from sentria_handler import SentriaHandler


def test_buffer_and_flush():
    sent_requests = []

    class MockResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, exc_type, exc_val, exc_tb): pass

    def mock_urlopen(req, timeout=None):
        sent_requests.append({
            "url": req.full_url,
            "data": req.data.decode("utf-8"),
            "headers": dict(req.headers)
        })
        return MockResponse()

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        handler = SentriaHandler(
            url="http://test-sentria:8000/ingest/raw",
            source="test-service",
            batch_size=100,
            flush_interval=60.0
        )
        logger = logging.getLogger("test_buffer_and_flush")
        logger.setLevel(logging.INFO)
        logger.handlers = [handler]

        logger.info("First message")
        logger.warning("Second message")

        assert len(sent_requests) == 0  # Still in buffer

        handler.flush()

        assert len(sent_requests) == 1
        assert "First message" in sent_requests[0]["data"]
        assert "Second message" in sent_requests[0]["data"]
        assert "source=test-service" in sent_requests[0]["url"]
        assert handler.sent_count == 2
        assert handler.dropped_count == 0

        handler.close()


def test_graceful_degradation_on_connection_error():
    def mock_urlopen(req, timeout=None):
        raise urllib.error.URLError("Connection refused")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        handler = SentriaHandler(
            url="http://unreachable-host:9999/ingest/raw",
            source="degraded-service",
            batch_size=100,
            flush_interval=60.0
        )
        logger = logging.getLogger("test_degrade")
        logger.setLevel(logging.INFO)
        logger.handlers = [handler]

        # Emitting should NOT raise an exception
        logger.error("Database connection lost")
        handler.flush()

        assert handler.dropped_count == 1
        assert handler.sent_count == 0

        handler.close()


def test_batch_size_trigger():
    sent_requests = []

    class MockResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, exc_type, exc_val, exc_tb): pass

    def mock_urlopen(req, timeout=None):
        sent_requests.append(req.data.decode("utf-8"))
        return MockResponse()

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        handler = SentriaHandler(
            url="http://test-sentria:8000/ingest/raw",
            source="batch-trigger-service",
            batch_size=3,
            flush_interval=60.0
        )
        logger = logging.getLogger("test_batch_trigger")
        logger.setLevel(logging.INFO)
        logger.handlers = [handler]

        logger.info("Msg 1")
        logger.info("Msg 2")
        # Under batch threshold
        time.sleep(0.05)
        assert len(sent_requests) == 0

        # Hits batch threshold of 3
        logger.info("Msg 3")
        time.sleep(0.2)  # Allow daemon thread to flush
        assert len(sent_requests) >= 1
        assert "Msg 1" in sent_requests[0]
        assert "Msg 2" in sent_requests[0]
        assert "Msg 3" in sent_requests[0]

        handler.close()


def test_close_flushes_remaining():
    sent_requests = []

    class MockResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, exc_type, exc_val, exc_tb): pass

    def mock_urlopen(req, timeout=None):
        sent_requests.append(req.data.decode("utf-8"))
        return MockResponse()

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        handler = SentriaHandler(
            url="http://test-sentria:8000/ingest/raw",
            source="close-service",
            batch_size=100,
            flush_interval=60.0
        )
        logger = logging.getLogger("test_close")
        logger.setLevel(logging.INFO)
        logger.handlers = [handler]

        logger.info("Pending log line")
        assert len(sent_requests) == 0

        # Close should synchronously flush
        handler.close()
        assert len(sent_requests) == 1
        assert "Pending log line" in sent_requests[0]
