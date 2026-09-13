# SELF-ASSIGNED TASK — AI-Powered Log Analysis & Incident Classification Platform
**Working name: Sentria** *(rename freely — update repo, manifests, and this doc if you do)*

---

## Overview

You already built the observability layer (`vuln-observability` — Loki, Grafana, Tempo, Prometheus). The gap in your portfolio isn't "can you ship logs somewhere," it's "can you make logs *useful* under pressure." Every infra team drowns in log volume; almost none of them have a system that tells an on-call engineer *what actually matters* at 3am.

Sentria closes that gap. It's an inference service that classifies incoming logs by severity/category, sits downstream of a log source, exposes its own health and performance as first-class metrics, and routes what it finds into an alerting path — all shipped through the same CI/CD and Kubernetes discipline you used on Continuum and SwiftDeploy.

You are not building a research-grade ML model. You are building the production home for one, and proving you understand why serving ML in production is operationally different from serving a normal API.

There is no external grader here. **You are the grader.** Each must-have below needs actual command output / screenshot evidence before you consider it done — same phase-gate discipline as Continuum. Don't mark something complete because the agent said it worked.

---

## What You Must Build

### 1. Log Source & Data Pipeline

**Must-haves:**
- A real or realistic stream of log lines feeding the classifier — not a static CSV loaded once
- Logs must have at minimum: `timestamp`, `source`, `level/status`, `message`
- A documented ingestion path from source → classifier (batch poll, streaming, or webhook — your call, see below)

**🔓 Your Decision (write a short ADR):**
- **Data source**: reuse your `vuln-observability` Loki instance as the origin (strongest narrative — "I built intelligence on top of my own observability stack"), OR use a public log dataset (e.g. LogHub-style HDFS/Linux/Apache logs) for known-good labels, OR generate synthetic logs with injected anomalies from a toy service. Document why.
- **Ingestion pattern**: does Sentria poll Loki's query API on an interval, tail a file, or receive logs pushed to it? State the tradeoff you're accepting (latency vs. complexity vs. coupling to Loki).

---

### 2. Classification / Inference Service

**Must-haves:**
- A single HTTP service (Python — FastAPI/Flask is fine) that accepts a log line or batch and returns a classification
- Minimum output per log entry: `category` (e.g. `error`, `warning`, `security`, `noise`) and `confidence` (0–1 float)
- Model must be loaded once at startup, not per-request (this is a correctness requirement — reloading per request is a real production bug you should be able to explain if asked)
- `GET /health` → liveness, must reflect whether the model is actually loaded, not just "process is up"
- `GET /metrics` → Prometheus text format (see Section 5)
- `POST /classify` → accepts one or more log lines, returns classifications
- Response time must be measured and exposed — no undocumented latency

**🔓 Your Decision (write a short ADR):**
- **Model approach**: pretrained transformer for text classification (e.g. a HuggingFace log/anomaly classifier), a simpler embedding + clustering/few-shot approach, or a rule-assisted classifier bootstrapped with ML for ambiguous cases. There is no wrong answer here — but you must be able to explain *why* you didn't need to train from scratch, and what you'd do differently if this had to be genuinely accurate in production.
- **Time-box this.** The moment you're tuning model accuracy for its own sake, you've drifted off the point of the project. Cap model experimentation at a fixed number of hours/days and move on — the platform is the deliverable, not the model.

---

### 3. Containerization

**Must-haves:**
- Multi-stage Dockerfile — final image contains no build tools, no dev dependencies
- Container runs as a non-root user
- Working `HEALTHCHECK` instruction tied to `/health`
- No model weights, secrets, or credentials baked into the image if avoidable — pull at startup or mount as a volume; if you must bake weights in, document why and the image size tradeoff
- Image size documented in README (inference images balloon fast — know your number and be able to justify it)

---

### 4. Kubernetes / EKS Deployment

**Must-haves:**
- Deployment manifest (raw YAML or Helm — your call, but you already have Helm reps from Continuum, so Helm is the stronger CV line) with resource `requests`/`limits` set deliberately, not copy-pasted defaults
- Readiness *and* liveness probes wired to `/health` — distinguish "model still loading" from "service is dead"
- Deployed to EKS (reuse Continuum's cluster if it's still live, or a fresh minimal cluster — don't spin up a second full DR-grade cluster just for this)
- Service exposed internally; no direct public exposure of the inference endpoint without a reason you can defend

**🔓 Your Decision (write a short ADR):**
- **Autoscaling metric**: CPU-based HPA is the lazy default and you should say so if you use it. The stronger answer — since this is inference-bound — is scaling on request latency or queue depth via a custom metric. If you don't implement this, at minimum document that you *identified* CPU-based autoscaling as the wrong signal for an inference workload and explain what the right one would be.

---

### 5. Observability (Prometheus + Grafana)

**Must-haves — the service must expose:**
- `inference_requests_total` (labels: `category`, `status_code`)
- `inference_latency_seconds` (histogram, standard buckets)
- `inference_confidence_score` (histogram or summary — this is the metric that makes this project *about ML observability* and not generic API observability)
- `model_loaded` (0/1 gauge)

**Grafana dashboard must show, at minimum:**
- Request rate and error rate over time
- P50/P95/P99 inference latency
- Confidence score distribution — flag if confidence is trending down over time (this is your proxy for "is the model degrading")
- Category breakdown (what's actually being classified as what, over time)

**🔓 Your Decision (write a short ADR):**
- Decide what you'd consider a genuine "drift" signal here — falling average confidence, a category distribution shift, or rising latency — and build one alert rule around it (even a simple Prometheus alert rule is enough). You don't need real drift-detection statistics; you need to demonstrate you understand *why* ML services need different monitoring than a CRUD API.

---

### 6. CI/CD (GitHub Actions or ArgoCD)

**Must-haves:**
- Pipeline stages, in order: lint → test → build → scan → deploy. A failure at any stage blocks the rest.
- At least 3 unit tests for the classification service (mock the model call — you're testing your service logic, not the model's accuracy)
- Image built, tagged with git SHA, pushed to a registry (Docker Hub is fine — you already use `michaelayz`)
- Trivy scan, fail on CRITICAL findings

**🔓 Your Decision (write a short ADR):**
- **GitHub Actions vs ArgoCD** — Actions push-based deploy is simpler and faster to ship; ArgoCD gives you GitOps and a stronger "platform engineering" story if you want to demonstrate pull-based reconciliation. Pick based on what CV story you're missing — if you already have strong CI/CD evidence from SwiftDeploy, ArgoCD may be the better differentiator here.
- **Deployment strategy on promotion**: plain rolling update is acceptable, but a confidence-gated or canary rollout (new model version only gets full traffic if its live confidence/error metrics hold for N minutes) is a direct callback to the OPA canary-gating you already built in SwiftDeploy 4B — strongly consider reusing that pattern here instead of reinventing it.

---

### 7. Confidence-Based Routing & Feedback Loop

**Must-haves:**
- Classifications below a configurable confidence threshold must be flagged separately (e.g. `needs_review: true` in the response), not silently treated as a confident answer
- A `POST /feedback` endpoint where a human can submit a correction for a given classification — persist it (even to a flat file or SQLite is fine, this isn't the hard part)
- Document in the README that this is a stub for a real retraining loop, and what the next step would be if this were production

*(This is the section that separates "I deployed a model" from "I understand ML lifecycle." Don't skip it, but don't over-build it either — a working stub beats a half-finished pipeline.)*

---

### 8. Alert Integration

**Must-haves:**
- High-severity classifications (or the drift alert from Section 5) route to Slack — reuse the Alertmanager/webhook pattern from `vuln-observability`
- Alert payload must include: category, confidence, source log excerpt (truncated), timestamp, link to the Grafana dashboard
- End-to-end proof: inject a log that should trigger a high-severity classification, screenshot it landing in Slack

---

## Repo Structure

```
sentria/
├── service/            # FastAPI app: main.py, model.py, metrics.py, feedback.py
├── ingestion/           # log source connector (Loki poller / tailer / webhook receiver)
├── k8s/                 # Helm chart or raw manifests
├── .github/workflows/   # or argocd/ if you go GitOps
├── dashboards/           # Grafana JSON, version-controlled
├── docs/
│   ├── architecture.png
│   └── decisions/        # your ADRs — one file per 🔓 decision above
├── screenshots/
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## Required Evidence (screenshot or terminal output — same discipline as Continuum)

1. `service-running.png` — service up, `/health` returning model-loaded true
2. `classify-request.png` — a real `curl`/Postman call to `/classify` with a live response
3. `metrics-endpoint.png` — raw `/metrics` output showing all four required metrics populated
4. `grafana-dashboard.png` — full dashboard with real traffic flowing through it
5. `drift-alert-fired.png` — your confidence/drift alert rule actually firing, not just defined
6. `slack-alert.png` — a high-severity classification landing in Slack end-to-end
7. `feedback-loop.png` — a correction submitted via `/feedback` and persisted
8. `pipeline-green.png` — full CI/CD pipeline passing lint → test → build → scan → deploy
9. `ci-blocked.png` — proof the pipeline actually blocks on a failure (deliberately break a test, show it stop)

---

## README Requirements

- What Sentria does, in one paragraph, without AI-marketing language — be precise about what the model actually does
- Architecture diagram showing log source → Sentria → Grafana/Slack
- All ADRs linked (`docs/decisions/`)
- Image size and why
- Fresh-cluster setup instructions, start to finish
- Known limitations — be honest about what this would need to become genuinely production-grade (real drift detection, model versioning/registry, retraining pipeline, etc.)

---

## DOs and DON'Ts

**DO:**
- Time-box the model selection — this is an infra project wearing an ML costume, not the reverse
- Reuse your existing patterns (OPA canary gating, Loki, Alertmanager/Slack) wherever they fit instead of reinventing them
- Write the ADRs *before* you build, the same way you did the Continuum EDD — decisions made under deadline pressure and written up after tend to be rationalized, not reasoned

**DON'T:**
- Claim "AI-powered" in your CV/README without being able to explain the model in one sentence to a technical interviewer
- Let scope creep turn this into a labeling/data-science project — if you find yourself hand-labeling thousands of logs, stop and simplify the dataset decision
- Skip the confidence/drift section — it's the cheapest section to build and the one that proves you understand *why* ML observability isn't the same as API observability

---

## Definition of Done

- [ ] All 8 "What You Must Build" sections have their must-haves met with evidence
- [ ] All 🔓 decisions have a short ADR in `docs/decisions/`
- [ ] All 9 required screenshots captured
- [ ] README complete and can take a stranger from clone to running cluster
- [ ] You can explain, out loud, in under 2 minutes: what the model does, why you chose it, how the confidence/drift signal works, and what you'd change for real production use

---

## Stretch (only after Definition of Done is fully met)

- Confidence-gated canary promotion for new model versions (direct reuse of your SwiftDeploy OPA pattern)
- A second classifier version deployed side-by-side (A/B) with traffic split, comparing confidence distributions live in Grafana
- Basic drift detection using a statistical test (KL divergence or PSI on category distribution over rolling windows) instead of a simple confidence-average threshold
