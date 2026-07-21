# ADR 4: Autoscaling Metric (Resource-based Scaling with Custom Metric Outlook)

## Context
We need to configure the autoscaling strategy for the Sentria inference service running on Kubernetes. Inference workloads are highly CPU-bound and can experience sudden traffic spikes. If the service fails to scale fast enough, requests will queue up, leading to high latency or timeouts.

## Decision
- **Initial Implementation**: We will deploy a Kubernetes `HorizontalPodAutoscaler` (HPA) targeting standard **CPU Utilization** (e.g., scale up when average CPU exceeds 70%) and **Memory Utilization**.
- **Production Guidance**: We document in this ADR and the README that CPU-based autoscaling is a lagging indicator for ML inference workloads. In a true production environment, the service should scale based on a custom metric like **Request Latency (P90/P95)** or **In-Flight Queue Depth**.

## Consequences
- **Ease of Setup**: Using CPU/Memory-based HPA allows us to deploy the application on standard Kubernetes/EKS clusters out-of-the-box, without installing the `Prometheus Adapter` or configuring Custom Metrics APIs.
- **Lagging Response Trade-off**: CPU metrics lag behind real-time traffic spikes because Kubernetes calculates average CPU usage over a window. This means the service may experience temporary latency spikes during sudden load increases before the HPA registers the CPU increase and provisions new pods.
- **Architectural Clarity**: The team has identified that queue depth/latency is the correct metric for inference scaling, meaning a future phase-gate can transition to scaling on custom Prometheus metrics without changing the service's internal architecture.
