"""
Sentria Python Logging Handler
Async, non-blocking, buffered logging handler with graceful degradation.
Zero external dependencies (uses standard library only).
"""
import atexit
import json
import logging
import sys
import threading
import time
import urllib.request
import urllib.error
from collections import deque
from typing import Optional


class SentriaHandler(logging.Handler):
    """
    Asynchronous, batching HTTP logging handler for Sentria.
    
    Features:
    - Non-blocking: logs are appended to an in-memory queue.
    - Automatic batching: flushes when `batch_size` is reached or `flush_interval` expires.
    - Graceful degradation: network failures or service downtimes drop logs silently
      without raising exceptions or blocking the host application.
    - Zero external dependencies: works with Python 3.8+ standard library.
    """

    def __init__(
        self,
        url: str = "http://localhost:8000/ingest/raw",
        source: str = "python-app",
        batch_size: int = 50,
        flush_interval: float = 5.0,
        max_buffer_size: int = 10000,
        timeout: float = 3.0,
        level: int = logging.NOTSET,
    ):
        super().__init__(level=level)
        self.url = url
        self.source = source
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.max_buffer_size = max_buffer_size
        self.timeout = timeout

        self.buffer = deque(maxlen=max_buffer_size)
        self._buffer_lock = threading.RLock()
        self.is_closed = False
        
        # Telemetry & error throttling
        self.dropped_count = 0
        self.sent_count = 0
        self.last_error_time = 0.0
        self.error_throttle_seconds = 60.0

        # Background timer for periodic flushing
        self.timer: Optional[threading.Timer] = None
        self._schedule_timer()

        # Register process exit hook
        atexit.register(self.close)

    def emit(self, record: logging.LogRecord) -> None:
        if self.is_closed:
            return

        try:
            msg = self.format(record)
            with self._buffer_lock:
                self.buffer.append(msg)
                should_flush = len(self.buffer) >= self.batch_size

            if should_flush:
                # Flush in a separate daemon thread so logging remains non-blocking
                threading.Thread(target=self.flush, daemon=True).start()
        except Exception:
            self.handleError(record)

    def _schedule_timer(self) -> None:
        with self._buffer_lock:
            if self.is_closed:
                return
            if self.timer is not None:
                self.timer.cancel()
            self.timer = threading.Timer(self.flush_interval, self._timer_flush)
            self.timer.daemon = True
            self.timer.start()

    def _timer_flush(self) -> None:
        try:
            self.flush()
        finally:
            self._schedule_timer()

    def flush(self) -> None:
        """
        Flushes the current log buffer to Sentria over HTTP.
        If Sentria is unreachable, logs are dropped safely without raising.
        """
        with self._buffer_lock:
            if not self.buffer:
                return
            items = list(self.buffer)
            self.buffer.clear()

        payload = "\n".join(items)
        if not payload.strip():
            return

        # Prepare HTTP request
        target_url = self.url
        if "?" in target_url:
            full_url = f"{target_url}&source={self.source}"
        else:
            full_url = f"{target_url}?source={self.source}"

        req = urllib.request.Request(
            full_url,
            data=payload.encode("utf-8"),
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "User-Agent": "sentria-python-handler/1.0"
            },
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                if 200 <= response.status < 300:
                    self.sent_count += len(items)
                else:
                    self._record_drop(len(items), f"HTTP {response.status}")
        except urllib.error.URLError as e:
            self._record_drop(len(items), str(e.reason))
        except Exception as e:
            self._record_drop(len(items), str(e))

    def _record_drop(self, count: int, reason: str) -> None:
        self.dropped_count += count
        now = time.time()
        # Throttled warning to stderr at most once every 60s
        if now - self.last_error_time > self.error_throttle_seconds:
            self.last_error_time = now
            sys.stderr.write(
                f"[SentriaHandler] Warning: Unable to send {count} log(s) to {self.url} "
                f"({reason}). Total dropped: {self.dropped_count}. Degrading gracefully.\n"
            )

    def close(self) -> None:
        with self._buffer_lock:
            if self.is_closed:
                return
            self.is_closed = True
            if self.timer is not None:
                self.timer.cancel()
                self.timer = None

        # Synchronous final flush
        self.flush()
        super().close()
