# Sentria Python Logging Handler

Lightweight, async, non-blocking HTTP logging handler with graceful degradation. Plugs directly into standard Python `logging`.

---

## Features

- **Zero External Dependencies**: Uses only Python 3.8+ standard library (`logging`, `urllib`, `threading`, `collections`).
- **Non-Blocking**: Calls to `logger.info(...)`, `logger.error(...)` never wait on HTTP network I/O.
- **Batching & Buffering**: Automatically batches logs by count (`batch_size=50`) or elapsed time (`flush_interval=5.0s`).
- **Graceful Degradation**: If Sentria goes offline or experiences latency spikes, logs drop silently without raising exceptions or degrading your application's throughput. Throttled warnings are printed to `stderr` at most once per minute.
- **Thread-Safe**: Safe for multi-threaded WSGI/ASGI servers (Gunicorn, Uvicorn, Celery).

---

## Quickstart

```python
import logging
from sentria_handler import SentriaHandler

# Create and attach handler
handler = SentriaHandler(
    url="http://localhost:8000/ingest/raw",
    source="payment-service",
    batch_size=50,         # Flush immediately when buffer hits 50 logs
    flush_interval=5.0,    # Or flush every 5 seconds
    timeout=2.0            # Network timeout in seconds
)

logger = logging.getLogger("my_app")
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# Forward logs effortlessly to Sentria
logger.info("Application worker started on pid %d", 1234)
logger.error("FATAL: database connection pool exhausted")
```

---

## Integration with Frameworks

### Django
In `settings.py`:
```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'sentria': {
            '()': 'sentria_handler.SentriaHandler',
            'url': 'http://sentria-host:8000/ingest/raw',
            'source': 'django-web',
            'batch_size': 20,
            'flush_interval': 3.0,
        },
    },
    'root': {
        'handlers': ['sentria'],
        'level': 'INFO',
    },
}
```

### FastAPI / Uvicorn
```python
import logging
from sentria_handler import SentriaHandler

@asynccontextmanager
async def lifespan(app: FastAPI):
    handler = SentriaHandler("http://localhost:8000/ingest/raw", source="fastapi-app")
    logging.getLogger().addHandler(handler)
    yield
    handler.close()
```
