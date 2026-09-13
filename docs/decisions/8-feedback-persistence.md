# ADR 8: Feedback Persistence & HPA Conflict

## Context
We are using an embedded SQLite database (`service/feedback.db`) to persist user feedback for human-in-the-loop log review. However, Kubernetes Horizontal Pod Autoscaler (HPA) will spin up multiple replicas of the FastAPI application under load. If multiple pods use local ephemeral SQLite files, feedback data will be fragmented across pods and lost entirely upon pod restart.

Furthermore, mounting a shared PersistentVolumeClaim (PVC) with `ReadWriteMany` access mode across multiple pods using SQLite is highly prone to database locking errors and corruption.

## Decision
For the MVP phase, we explicitly **pin replicas: 1** in the Helm chart and mount a 1Gi `PersistentVolumeClaim` (PVC, `ReadWriteOnce`, `gp3` storageClass) at the feedback database location (`/app/service/data`). 

- **Single Replica (`replicas: 1`)**: Avoids `ReadWriteMany` SQLite lock contention across concurrent pod instances.
- **Persistent Volume Claim (PVC)**: Guarantees that human-in-the-loop feedback submitted via `POST /feedback` is preserved across pod restarts, node reschedules, and Helm redeployments.
- **Production Migration Path**: If horizontal auto-scaling (HPA) is required under high load, the SQLite database and PVC will be replaced by a managed PostgreSQL instance (e.g. AWS RDS).

## Consequences
- Human feedback data persists across pod lifecycle events.
- Prevents database locking errors and corruption.
- **Limitation**: The service is constrained to `replicas: 1` throughput until migrated to an external database.

