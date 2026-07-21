# ADR 7: Slack Alert Trigger Rule

## Context
Sentria classifies incoming logs into `noise`, `warning`, `error`, and `security` categories. A critical requirement is routing actionable logs to an on-call engineer via Slack (using Alertmanager or webhook). However, not all `error` or `security` logs require immediate human intervention, and conversely, logs that the model is uncertain about may hide subtle anomalies that require an engineer's judgment.

We need explicit rules mapping category and confidence combinations to distinct Slack alert severities, ensuring humans only receive context-rich, prioritized notifications without suffering from alert fatigue.

## Decision
We define three distinct Slack alert triggers:

### 1. High-Confidence Incident (Standard Routing)
- **Condition**: `Category in [error, security]` AND `Confidence >= 0.75`
- **Action**: Fire a standard `High Severity` Slack alert. 
- **Rationale**: The model is confident an incident has occurred. The alert payload will include the log snippet, the identified category, and a link to the relevant Grafana dashboard.

### 2. Low-Confidence Anomaly (Human Review Required)
- **Condition**: `Category in [error, security]` AND `Confidence < 0.75`
- **Action**: Fire a `CRITICAL: Human Review Required` Slack alert.
- **Rationale**: These are the most dangerous edge cases. The model suspects an incident but is unsure (ambiguous anomaly). These logs are explicitly prioritized and flagged with `needs_review: true` via the API. The Slack alert will explicitly request the on-call engineer to review the raw log and submit a correction via the `/feedback` endpoint to improve future model generations.

### 3. Systemic Model Drift
- **Condition**: The Prometheus rolling average `inference_confidence_score` falls below `0.70` over a 5-minute window.
- **Action**: Fire a `WARNING: Model Drift Detected` Slack alert.
- **Rationale**: Signals that the distribution of incoming logs has fundamentally changed, meaning the underlying application logging pattern has shifted and the model's training dataset is now stale.

## Consequences
- Reduces alert fatigue by separating confident classification from ambiguous logs.
- Directs engineer attention to logs that will actively improve the model's accuracy via the `/feedback` loop.
- Ensures systemic drift is tracked independently of individual request anomalies.
