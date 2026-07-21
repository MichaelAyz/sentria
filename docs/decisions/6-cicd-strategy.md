# ADR 6: CI/CD Strategy (GitHub Actions and Helm Rollout Gating)

## Context
We need to automate the testing, containerization, scanning, and deployment of Sentria. The pipeline must ensure that no broken code, failing tests, or critical security vulnerabilities make it to our Kubernetes cluster. We also want a deployment strategy that lets us introduce canary promotion gates in the future (matching OPA policies from previous architectures) without rewriting the core deployment setup.

## Decision
We will implement a **GitHub Actions Push-based Pipeline** paired with **Helm-managed Kubernetes Deployments**:
1. **Pipeline Stages**:
   - **Lint**: Run code style checks (e.g. `flake8` or `black`).
   - **Test**: Run unit tests (with model mock implementations to speed up CI and avoid caching heavy models).
   - **Build**: Compile multi-stage Docker image, tagged with the git commit SHA.
   - **Scan**: Run Trivy vulnerability scan against the image, failing the pipeline if any `CRITICAL` issues are found.
   - **Deploy**: Upgrade the Helm release on Kubernetes.
2. **Promotion Strategy**:
   - The initial deployment strategy will be a **Rolling Update** managed by Helm.
   - We will structure the Helm templates and naming conventions to support **Canary Tracks** (e.g., separate `sentria-canary` and `sentria-stable` deployments/services). This ensures we can easily plug in a metrics-based/OPA gate later without refactoring our templates.

## Consequences
- **Security Gates**: Trivy scanning guarantees that high-risk base image issues block deployment before reaching production.
- **Fail-Fast**: Any unit test or lint failure halts the pipeline immediately, protecting the target environment from unstable builds.
- **Canary Readiness**: Although we start with rolling updates, our Helm layout keeps the deployment modular, meaning we can easily support a canary promotion flow (comparing canary vs. stable confidence metrics) in future iterations.
