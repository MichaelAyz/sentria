# ADR 1: Data Source Selection (Synthetic Log Generator)

## Context
Sentria requires a realistic, continuous stream of log data to classify. Our development environment does not currently have a running Loki log aggregation instance or active AWS credentials to poll. Standard public log datasets (like LogHub) provide realistic log formats but are static and lack the ability to interactively inject specific anomalies to trigger and test downstream alerts and routing under pressure.

## Decision
We will build a custom **Synthetic Log Generator** (`ingestion/generator.py`).
- **Log Format**: The generated log lines will mimic production web servers, authentication systems, and database engines. Each log entry will include:
  - `timestamp` (ISO 8601 string)
  - `source` (e.g., `auth_service`, `db_primary`, `api_gateway`)
  - `level` (e.g., `INFO`, `WARNING`, `ERROR`, `CRITICAL`)
  - `message` (structured or unstructured log messages)
- **Anomalies**: The generator will be able to inject specific patterns (e.g., SSH brute force, SQL injection, database connection timeouts, memory exhaustion) on demand or on a configured schedule.
- **Evaluation Labels**: To solve the cold-start problem and evaluate model performance, the generator will tag each log with an internal `true_label`/`injected_type` field (e.g., `noise`, `security`, `error`, `warning`).

## Consequences
- **Offline Evaluation**: The generator will have a **Batch Mode** that exports a CSV of labeled logs. This dataset will be used by `training/train.py` to train and evaluate the machine learning model.
- **No Loki Dependency**: We do not need a running Loki stack to test Sentria's capabilities, eliminating operational coupling during initial phases.
- **Free Labels**: Injected anomalies translate directly to labeled training data for free, allowing us to evaluate classification accuracy.
- **True Label Masking**: The internal `true_label`/`injected_type` field will only be used for model training and local validation. It will *never* be sent to the FastAPI `/classify` endpoint during streaming mode, nor will it be exposed via any public client APIs.
