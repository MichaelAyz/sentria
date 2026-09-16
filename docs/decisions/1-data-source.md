# ADR 1: Data Source Selection (Real Multi-System Log Harvesting & Drain3 Template Clustering)

## Context
Sentria requires diverse, realistic log data to classify across operational categories (`error`, `warning`, `security`, `noise`). Early prototypes relied on synthetic log generators with programmed anomalies. However, synthetic generation suffers from critical flaws:
1. **Shortcut Trap & Data Leakage**: Keyword-driven synthetic logs lead models to learn trivial token correlations rather than semantic intent, causing models that score artificially high (>95%) on synthetic benchmarks to degrade sharply (<50%) on real unseen infrastructure logs.
2. **Lack of Structural Diversity**: Production systems emit complex, heterogeneous log formats, including syslog headers, nested JSON payloads, microservice trace IDs, and multi-line exception stack traces across different language runtimes.
3. **Evaluation Rigor**: An inference service deployed downstream of enterprise log forwarders requires an immutable, realistic held-out test suite to measure true generalization.

## Decision
We transitioned from synthetic generation to **Real Multi-System Log Harvesting & Template Mining**:
- **Multi-Source Ingestion (`training/harvest/harvest_pipeline.py` & `training/capture/capture_services.py`)**:
  - Ingested 38,416+ real production log lines spanning 18 distinct environments (Loghub enterprise datasets including Linux, Apache, Hadoop, OpenStack, Spark, Zookeeper, Mac, Windows, alongside live Docker/Kubernetes container logs from Nginx, PostgreSQL, Redis, Next.js/Node.js, SSH authentication daemons, and Acunetix security probe archives).
- **Structural Mining via Drain3**:
  - Applied the Drain3 online log parsing algorithm to cluster structurally similar log messages into template signatures, extracting 1,788 unique structural templates.
  - Ensured balanced representation across all four operational categories without allowing any single system to skew classification boundaries.
- **Zero-Leakage Stratified Splitting (`training/capture/split_dataset.py`)**:
  - Normalized all logs to generalized template signatures (masking timestamps, IPs, ports, dynamic numeric IDs, and hex addresses).
  - Enforced zero template signature overlap between the training partition (`training/data/train_logs.jsonl`) and the held-out evaluation datasets.
- **Cryptographic Blind Held-Out Set (`training/data/blind_test_logs.jsonl`)**:
  - Locked an immutable blind test set of $N=20$ samples per class ($N=80$ total) under a SHA-256 digest recorded in `training/data/blind_test_logs.lock` (`14a29b61e781...`).

## Consequences
- **Generalization Across Diverse Stacks**: The model evaluates raw log semantics rather than synthetic token artifacts, correctly categorizing unseen errors from varying operating systems and frameworks.
- **Honest Performance Verification**: `training/evaluate_blind.py` validates pipeline accuracy against an audit-grade, leak-free test partition.
- **Synthetic Script Deprecation**: Legacy generator scripts (`ingestion/generator.py`, `training/curate_data.py`) have been deprecated and removed in favor of reproducible harvesting pipelines.
