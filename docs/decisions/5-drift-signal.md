# ADR 5: Drift Signal (Rolling Average Prediction Confidence)

## Context
Machine learning models suffer from model degradation or drift over time. This happens when the distribution of incoming logs deviates from the training dataset distribution (data drift/concept drift). For example, a new service version might log entirely new error formats, causing the model to misclassify them or classify them with very low confidence. We need a way to detect this drift and trigger alerts without incurring the complexity of streaming statistical tests (like KL Divergence or Population Stability Index) on the active inference path.

## Decision
We will monitor the **rolling average of prediction confidence scores** as a proxy for drift:
- The FastAPI application will record the confidence score of each prediction.
- We will expose this metric as a Prometheus histogram or gauge: `inference_confidence_score`.
- We will write a Prometheus Alertmanager rule: if the rolling average of classification confidence falls below a threshold (e.g., `0.70`) over a 5-minute window, trigger a **Model Drift Alert**.

## Consequences
- **Low Overhead**: Keeping a running average of confidence scores requires negligible CPU and memory, ensuring inference remains fast.
- **Actionable Signal**: A sustained drop in confidence suggests the model is encountering logs it was not trained on, signaling that the training set needs updating or the model needs retraining.
- **Statistical Simplicity**: This avoids complex offline data drift calculations (like KL divergence or PSI) for the initial MVP, while providing a clear hook to implement them as a stretch goal.
