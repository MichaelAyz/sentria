# Sentria

> **Zero-Noise Log Triage and Incident Root-Cause Engine.**  
> Built to correlate cascading microservice outages in milliseconds using embedded, CPU-optimized machine learning.

---

## 1. The Problem: What Breaks at 2:00 AM

Every on-call engineer knows this nightmare:

A primary database runs out of connection slots. Instead of getting one clear message saying *"Database connection pool exhausted"*, **every service in your cluster panics at the same time**.

- The payment API times out.
- The order service drops worker threads.
- Nginx starts throwing hundreds of `502 Bad Gateway` errors.
- The ingress controller floods your monitoring channels.

Within two minutes, your terminal is overwhelmed with tens of thousands of lines of raw logs. You find yourself running frantic `grep` commands across terminal windows, trying to answer the only question that matters: **What actually broke first?**

**99% of server logs are routine background noise** (200 OKs, health checks, cron heartbeats). When a real failure happens, the signal gets buried under megabytes of noise.

---

## 2. The Machine Learning Challenge (And Why Most "AI" Log Tools Fail)

When people try to apply machine learning to logs, they usually hit three roadblocks:

1. **LLMs are too slow, expensive, and insecure for log streams**:  
   Calling cloud LLM APIs (like GPT-4 or Claude) takes 1 to 2 seconds per request, costs money per token, and leaks internal IP addresses, tokens, and user data outside your network. When a cluster emits 5,000 logs a second during an incident, an LLM API will either crash your budget or get rate-limited instantly.
2. **Regex keywords are too fragile**:  
   A rule matching `"error"` triggers false alarms on harmless logs like `INFO: Error rate dropped below 1% (recovered)`. Meanwhile, it completely misses critical kernel failures like `nf_conntrack: table full, dropping packet` because the word "error" never appears.
3. **The Shortcut Trap (Data Leakage)**:  
   During early development, our model showed a suspicious **96.8% accuracy**. When we audited the code, we found the culprit: auxiliary feature flags were checking for keywords like `"fatal"` or `"denied"` — the exact same words our labeling script had used! The model was taking a shortcut instead of understanding the semantics of the text. When fed genuine unseen logs, accuracy dropped to 48%.

### How We Solved the ML Problem
- We **ripped out all shortcut keyword flags**.
- We trained the model purely on **dense 384-dimensional semantic embeddings** using `all-MiniLM-L6-v2`.
- We built an automated harvesting pipeline using **Drain3** template mining, ingesting **38,416 real production logs across 18 enterprise systems** (Linux, Mac, Windows, Spark, Hadoop, Zookeeper, Kubernetes, PostgreSQL, Nginx, Redis, and real Acunetix web attack archives) to extract **1,788 structurally unique templates**.
- We locked an immutable blind test set with **SHA-256** (`14a29b61e781...`) with an enforced sample size of $N=20$ per class.
- The result is an honest, leak-free **82.50% accuracy** (FP32) and **81.25% accuracy** (INT8 quantized) running entirely on CPU.

---

## 3. How Sentria Works

Sentria processes logs in four sequential steps:

1. **Multi-Line Continuation Stitcher**: Automatically recognizes stack traces from Python, Node.js, and Java, fusing multi-line errors into single cohesive log entries.
2. **Dynamic Prefix Stripper**: Strips timestamps, process IDs, and syslog host headers so the model evaluates the semantic meaning of the message rather than transient metadata.
3. **Quantized ONNX Embedder & Classifier**: Converts cleaned text into a 384-dimensional dense vector using an embedded INT8 MiniLM transformer (`model_quantized.onnx`, 21.9 MB footprint) in ~32ms on standard CPU, then outputs category and confidence scores. The INT8 model is tracked in Git for immediate deployment upon clone, while the large FP32 reference model (`model.onnx`, 86.2 MB) is excluded via `.gitignore` to prevent repository bloat.
4. **Sliding-Window Incident Engine (ΔT = 120s)**: Correlates related errors occurring within 120 seconds. If events share an attacker IP or host, the window expands up to 300 seconds to catch distributed probes. It then identifies the primary root cause ($T_0$) using timestamp resolution and infrastructure tiebreaker heuristics.

---

## 4. Engineer & User Flow

Sentria supports two primary workflows: interactive triage for on-call engineers, and automated pipeline streaming for platform infrastructure.

### Flow A: The On-Call Triage Flow (Web Interface)
1. **Input**: During an incident, the engineer opens the Sentria web UI at `http://localhost:8000`. They can paste raw terminal output, drag and drop a `.log` file, or select a preset scenario.
2. **Instant Triage**: In under 15 milliseconds, the Executive Triage Bar displays overall cluster health, the count of critical vs. routine events, and top suspicious IP addresses. Routine 200 OKs and background syncs are suppressed from view.
3. **Root Cause Identification**: If multiple services failed, Sentria renders an **Incident Card**. It outlines the blast radius (which microservices were impacted), identifies the original root-cause log (e.g. Postgres connection limit), and provides actionable remediation steps (e.g. PgBouncer tuning).
4. **Active Learning**: If an engineer notices an ambiguous edge case, they click **"Suggest Correction"** on the card. This saves the feedback into an embedded store to queue continuous retraining.

### Flow B: The Production Streaming Flow (Platform & DevOps)
1. **Drop-in SDK or Agent**: Developers add the zero-dependency Python `SentriaHandler` (or Node.js client) to their services, or drop a Fluent Bit / Vector configuration into their host forwarders.
2. **Non-Blocking Background Shipping**: Logs are buffered in an in-memory queue and shipped in batches to `POST /ingest/raw`. Network calls never block the host application's request thread.
3. **Graceful Degradation**: If the Sentria service is ever offline or unreachable, the client handlers drop logs silently without raising exceptions or degrading service throughput.
4. **Observability**: Cluster monitoring automatically discovers and scrapes Sentria's Prometheus `/metrics` endpoint to monitor inference throughput, confidence distributions, and latency in Grafana.

---

## 5. Benchmark Results (Locked Blind Evaluation)

Evaluated against the frozen, SHA-256-locked blind test set ($N=20$ samples per category, zero overlap with training data):

| Metric | FP32 ONNX (`model.onnx`) | INT8 Quantized (`model_quantized.onnx`) | Impact / Notes |
| :--- | :---: | :---: | :--- |
| **Model Size** | 86.22 MB | **21.91 MB** | **74.6% reduction (4x smaller)** |
| **P50 Latency (Single Log)** | 48.1 ms | **41.6 ms** | Runs CPU-only |
| **Batch Latency (80 logs)** | 4,444 ms | **2,989 ms** | **1.5x speedup on batch CPU** |
| **Overall Pipeline Accuracy** | **82.50%** | **81.25%** | Only 1.25% trade-off for INT8 |
| **Macro F1 Score** | **0.8218** | **0.8097** | Balanced across all 4 classes |
| **Noise F1 Score** | 0.884 | **0.884** | Routine traffic suppressed |
| **Security F1 Score** | 0.857 | **0.829** | Attacks & probes isolated |
| **Error F1 Score** | 0.789 | **0.769** | Critical failures caught |
| **Warning F1 Score** | 0.757 | **0.757** | Saturation thresholds flagged |

---

## 6. Developer Ingestion Suite (How to Send Logs)

Sentria is designed for plug-and-play adoption across terminal tools, application runtimes, and standard log collectors.

### 1. Direct HTTP / cURL (Plaintext or JSON)
Stream raw log files directly without formatting JSON:

```bash
# Pipe raw log files directly to Sentria
curl -X POST "http://localhost:8000/ingest/raw?source=production-api" \
  -H "Content-Type: text/plain" \
  --data-binary @/var/log/nginx/error.log

# Or send multi-line strings directly:
curl -X POST "http://localhost:8000/ingest/raw?source=auth-service" \
  -H "Content-Type: text/plain" \
  -d $'FATAL: database connection pool exhausted\n502 Bad Gateway while connecting to upstream'
```

### 2. Python SDK (`sdks/python/sentria_handler.py`)
Zero external dependencies (Python standard library only). Uses a bounded in-memory queue (`collections.deque`), background worker thread, and **graceful degradation** (if Sentria is down, your application never crashes or slows down):

```python
import logging
from sdks.python.sentria_handler import SentriaHandler

# Attach Sentria non-blocking handler to your logger
handler = SentriaHandler(
    url="http://localhost:8000/ingest/raw",
    source="payment-service",
    batch_size=50,         # Flush every 50 logs
    flush_interval=5.0     # Or every 5 seconds
)
logging.getLogger().addHandler(handler)

# Standard logging calls stream to Sentria in the background
logging.error("FATAL: connection pool exhausted after 30000ms")
logging.warning("Slow query execution: 3200ms latency on /checkout")
```

### 3. Node.js Client (`sdks/node/sentria.js`)
Zero external dependencies (native Node.js `http`/`https` only). Plugs into `console`, **Winston**, or **Pino**:

```javascript
const { createHandler } = require('./sdks/node/sentria');

const sentria = createHandler({
  url: 'http://localhost:8000/ingest/raw',
  source: 'web-api-node',
  batchSize: 50,
  flushInterval: 5000,
});

sentria.error('FATAL: Database connection timeout');
sentria.warn('Approaching connection limit: 92%');

// Compatible as a Winston transport:
// logger.add(sentria.winstonTransport());
```

### 4. Log Forwarders (Fluent Bit / Vector / Logstash)
Ready-to-use configuration recipes are available in [`docs/recipes/`](./docs/recipes/):
- `docs/recipes/fluent-bit.conf`
- `docs/recipes/vector.toml`
- `docs/recipes/logstash.conf`

---

## 7. Quickstart: Running Sentria Locally

### Prerequisites
- Python 3.10+
- (Optional) Docker

### 1. Clone & Setup Virtual Environment
```bash
git clone https://github.com/MichaelAyz/sentria.git
cd sentria

python -m venv venv
# On Linux/macOS:
source venv/bin/activate
# On Windows:
.\venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Run the Service
```bash
uvicorn service.main:app --host 127.0.0.1 --port 8000
```

Open your browser to:
**[http://localhost:8000](http://localhost:8000)**

### 3. Using the Web Interface
- **PASTE TEXT**: Paste terminal output or log snippets.
- **UPLOAD FILE**: Drag and drop `.log` or `.csv` files.
- **PRESETS**: Test ready-made scenarios (SSH Brute Force, Postgres Pool Crash, Ambiguous Warnings).
- **API & SDKs**: View code recipes and click **"⚡ TEST IN WORKSPACE"** to test streaming simulation with incident grouping.
- **`>_ TERMINAL` Drawer**: Click the terminal button in the header to run live commands (`status`, `ingest`, `reload`).

---

## 8. Kubernetes & Production Deployment

Sentria is Kubernetes-ready out of the box.

### Docker
```bash
# Build the image
docker build -t sentria:latest .

# Run container
docker run -p 8000:8000 sentria:latest
```

### Helm Chart (`k8s/sentria`)
```bash
# Install or upgrade via Helm
helm upgrade --install sentria ./k8s/sentria \
  --set image.repository=sentria \
  --set image.tag=latest \
  --set service.type=ClusterIP
```

### Health Probes & Observability
- **Health Check**: `GET /health` (returns `200 OK` once ONNX model is loaded and warmed).
- **Prometheus Metrics**: `GET /metrics` exports latency histograms, `INFERENCE_REQUESTS` counts by category, and `INFERENCE_CONFIDENCE` observations.
- **Runtime Stats**: `GET /api/stats` returns operational state and collected active learning feedbacks.

---

## 9. Running the Test Suite

Run the full automated test suite (all 27 service and SDK tests):

```bash
# Python service and SDK tests
python -m pytest service/tests sdks/python/test_handler.py -v

# Node.js SDK tests
node sdks/node/test_handler.js

# Verify blind test set integrity (SHA-256 locked)
python -X utf8 training/evaluate_blind.py
```

---

## 10. Project Directory Layout

```
Sentria/
├── service/
│   ├── main.py              # FastAPI server, /classify & /ingest/raw endpoints
│   ├── model.py             # Inference manager with keyword safety fallback
│   ├── embedder.py          # ONNX Runtime MiniLM embedder (FP32 & INT8)
│   ├── features.py          # Dynamic prefix cleaning (signal extraction)
│   ├── stitcher.py          # Stack trace continuation stitcher
│   ├── incidents.py         # Sliding-window incident clustering & RCA engine
│   ├── metrics.py           # Prometheus instrumentation middleware
│   ├── feedback.py          # SQLite active-learning feedback store
│   ├── onnx/
│   │   ├── model_quantized.onnx # Active production runtime model (INT8, 21.9 MB, tracked)
│   │   ├── model.onnx           # Baseline reference model (FP32, 86.2 MB, gitignored)
│   │   └── tokenizer.json       # HuggingFace Fast Tokenizer
│   └── tests/               # 23 unit and integration tests
├── training/
│   ├── harvest/             # Drain3 harvesting pipeline (38k+ real logs)
│   ├── capture/             # Live container log collectors & splitters
│   ├── data/                # SHA256-locked blind test set & training data
│   ├── train_linear.py      # Retrains classification head on pure embeddings
│   └── evaluate_blind.py    # Zero-leakage evaluation against locked test set
├── sdks/
│   ├── python/              # Zero-dependency async logging handler & tests
│   └── node/                # Zero-dependency Node.js client, Winston adapter & tests
├── docs/recipes/            # Fluent Bit, Vector, and Logstash configurations
├── k8s/sentria/             # Complete Kubernetes Helm chart
├── static/
│   └── index.html           # Single-file interactive web dashboard
├── Dockerfile               # Production container image definition
└── requirements.txt         # Pinned Python dependencies
```

---

## 11. License

This project is licensed under the MIT License.
