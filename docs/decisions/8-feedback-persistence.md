# ADR 8: Feedback Persistence & HPA Conflict

## Context
We are using an embedded SQLite database (`service/feedback.db`) to persist user feedback for human-in-the-loop log review. However, Kubernetes Horizontal Pod Autoscaler (HPA) will spin up multiple replicas of the FastAPI application under load. If multiple pods use local ephemeral SQLite files, feedback data will be fragmented across pods and lost entirely upon pod restart.

Furthermore, mounting a shared PersistentVolumeClaim (PVC) with `ReadWriteMany` access mode across multiple pods using SQLite is highly prone to database locking errors and corruption.

## Decision
For the MVP phase, we explicitly **pin replicas: 1** in the Helm chart. We accept the limitation that the service will not automatically scale out horizontally to handle spikes, effectively disabling HPA. 
If/when scale-out is required for production inference traffic, we must replace SQLite with a centralized PostgreSQL database before re-enabling HPA.

## Consequences
- Prevents data fragmentation and data loss for human feedback.
- Simplifies MVP deployment (no Postgres dependency).
- **Limitation**: The service cannot scale horizontally. We are bound by the throughput of a single pod.
