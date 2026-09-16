# ADR 2: Ingestion Pattern (Multi-Modal Streaming Ingestion & Continuation Stitching)

## Context
Production log producers are heterogeneous and distributed. They originate from application processes (Python services, Node.js APIs), host log forwarders (Fluent Bit, Vector, Logstash), and ad-hoc engineer workflows (terminal streaming via cURL). 

A production log triage platform faces three primary ingestion requirements:
1. **Multi-Line Exception Integrity**: Critical errors in Python, Node.js, and Java span multiple lines (stack traces). Naive line-by-line ingestion breaks stack frames into isolated, misleading entries, destroying incident context.
2. **Non-Blocking Resilience**: Application logging handlers must never block host request-handling threads or throw unhandled exceptions if the triage service is temporarily unavailable or restarting.
3. **Flexible Protocols**: Systems must be able to push logs via native HTTP (`text/plain`, `application/json`), standard logging frameworks (Winston, Python `logging`), or enterprise daemon collectors without complex broker infrastructure.

## Decision
We implemented a **Multi-Modal Streaming Ingestion Pipeline**:

### 1. Dual Ingestion Endpoints in FastAPI
- **`POST /classify`**: High-performance structured endpoint accepting batch JSON payloads for direct service-to-service classification.
- **`POST /ingest/raw`**: Streaming plaintext and JSON endpoint. Accepts raw piped streams (`curl -X POST --data-binary @app.log ...`), strips syslog/host headers dynamically, and executes continuation stitching.

### 2. Multi-Line Continuation Stitcher (`service/stitcher.py`)
- Sits on the raw ingestion path to identify stack traces across runtimes:
  - Python (`Traceback (most recent call last):`, `File "...", line ...`)
  - Node.js / V8 (`Error: ...`, `    at Function...`)
  - Java / JVM (`Exception in thread ...`, `    at com.example...`, `Caused by: ...`)
- Fuses indented continuation frames into a single cohesive log entity prior to semantic embedding and incident correlation.

### 3. Zero-Dependency Client SDKs (`sdks/python/` & `sdks/node/`)
- Developed standard-library-only clients with no external runtime dependencies:
  - **Python (`SentriaHandler`)**: Plugs directly into standard Python `logging`. Employs a bounded in-memory `collections.deque` and a dedicated daemon background worker thread.
  - **Node.js (`sentria.js`)**: Compatible with native `console`, Winston, and Pino. Utilizes native `http`/`https` agents.
- **Buffer & Flush Triggers**: Dispatches payloads either when `batch_size` is reached (default: 50 logs) or when `flush_interval` expires (default: 5.0 seconds).
- **Graceful Degradation**: If Sentria is unreachable or encounters HTTP errors, logs are safely dropped in the background. Network exceptions are swallowed to guarantee zero impact on host application availability or throughput.

### 4. Enterprise Forwarder Configurations (`docs/recipes/`)
- Provided ready-to-deploy recipes for standard collectors:
  - `docs/recipes/fluent-bit.conf` (HTTP output plugin to `/ingest/raw`)
  - `docs/recipes/vector.toml` (HTTP sink with batching)
  - `docs/recipes/logstash.conf` (HTTP output codec)

## Consequences
- **Zero Request-Path Overhead**: Applications retain predictable sub-millisecond logging overhead regardless of inference cluster load.
- **Full Exception Context**: Stack traces are analyzed as unified records, providing the incident clustering engine with complete error traces.
- **Low Operational Overhead**: Bypasses the need for intermediate Kafka or RabbitMQ clusters while maintaining production-grade backpressure handling.
