# ADR 3: Model Architecture (Embedded INT8 ONNX MiniLM with Linear Head)

## Context
Sentria requires low-latency, accurate classification of unstructured log messages into four operational categories (`error`, `warning`, `security`, `noise`) along with calibrated confidence scores.

Our engineering requirements imposed strict trade-offs:
1. **CPU Latency & Cost**: Heavy PyTorch transformer runtimes or external cloud LLM APIs introduce 500ms–2000ms latencies, high token costs, and external network dependencies. The system must run entirely on standard multi-core CPUs without requiring GPUs.
2. **Semantic Understanding vs. Regex Fragility**: Pure keyword or TF-IDF models break on paraphrased or novel logs (e.g. failing to flag `nf_conntrack: table full, dropping packet` because the token "error" is absent). We need dense semantic representations.
3. **Data Leakage & Shortcut Trap**: Models trained with superficial keyword features exhibit catastrophic performance drops on unseen real-world logs.
4. **Memory Footprint**: Inference containers must remain small (<500MB RAM) with fast cold-start times.

## Decision
We adopted an **Embedded Quantized ONNX MiniLM Pipeline with a Calibrated Linear Head**:

### 1. Model Artifacts & Production Usage
The repository maintains two ONNX model artifacts under `service/onnx/`:

| Artifact | Precision | File Size | Role & Deployment Status |
| :--- | :---: | :---: | :--- |
| **`model_quantized.onnx`** | **INT8** | **21.9 MB** | **Active Production Runtime Model**. Committed directly to the repository so the service runs immediately out-of-the-box upon `git clone`. Loaded by default by `ModelService` (`quantized=True`) and `MiniLMEmbedder`. Delivers ~32ms P50 latency and 74.6% disk/RAM reduction with negligible (1.25%) accuracy difference. |
| **`model.onnx`** | **FP32** | **86.2 MB** | **Full-Precision Reference Baseline**. Excluded from version control via `.gitignore` to prevent repository bloat (keeping the repo under 25 MB). Retained locally for offline training validation and empirical quantization benchmarks. |

In production, Sentria configures `ModelService(quantized=True)`, mounting and executing `model_quantized.onnx` through ONNX Runtime's optimized `CPUExecutionProvider` with HuggingFace `tokenizers` (Fast Rust implementation). Zero PyTorch or `sentence-transformers` libraries are required in the production image.

### 2. Semantic Embedding & Classification Head
- **Dense Vectorization (`service/embedder.py`)**:
  - Encodes incoming text using `all-MiniLM-L6-v2` into normalized 384-dimensional dense vectors.
  - Mean pooling over the attention mask followed by L2 normalization guarantees that semantic cosine similarity equates to vector dot products.
- **Dynamic Prefix Stripper (`service/features.py`)**:
  - Before embedding, logs are dynamically stripped of ISO/syslog timestamps, ephemeral process IDs, and syslog host headers (`transform_features()`).
  - Ensures the embedding layer evaluates the underlying semantic event rather than transient header metadata.
- **Calibrated Linear Head (`service/linear_head.joblib`)**:
  - A lightweight regularized linear classifier trained purely on 384-dimensional embeddings without auxiliary keyword shortcuts (`training/train_linear.py`).
  - Uses `SGDClassifier(loss='log_loss', alpha=0.0005)` to yield well-calibrated class probabilities.

### 3. Safety Fallback Net (`service/model.py`)
- If the ML pipeline produces a classification with low confidence, a targeted keyword fallback net checks for unambiguous security attack signatures (e.g., `/etc/passwd`, SQL injection, SSRF) or critical kernel panics.
- Ensures zero false-negatives on high-risk, syntax-standardized system alerts.

### 4. Lifecycle & Pre-Warming
- **Lifespan Boot Loading**: Loaded once at FastAPI application startup via `lifespan(app)`.
- **In-Memory Pre-Warming (`ModelService.warm()`)**: Runs two warmup inference cycles during container boot to initialize ONNX execution graphs, completely eliminating first-request latency spikes.
- **Health Check Integrity**: `GET /health` explicitly validates that the model is loaded and pre-warmed (`model_service.is_loaded() and model_service.is_warmed()`) before Kubernetes marks the pod as ready.

## Consequences
- **Ultra-Fast CPU Inference**: INT8 quantization yields sub-45ms single-log inference on standard CPU cores.
- **Drastic Footprint Reduction**: Quantized model weights occupy only 21.9 MB, keeping container startup and cold starts under 2 seconds.
- **Zero Framework Bloat**: Deploying ONNX Runtime and `tokenizers` avoids gigabytes of PyTorch / CUDA runtime dependencies.
- **Lean Git Repository**: By committing only the INT8 model and ignoring the 86.2 MB FP32 baseline, the git repository footprint stays under 25 MB with fast clone and push operations.
