# ADR 9: Secret Management for Slack Webhook

## Context
Sentria requires a Slack webhook URL to route high-severity alerts and model drift warnings (as defined in ADR 7). We must ensure this sensitive URL is handled securely across the development lifecycle.

## Decision
- **Never Hardcode**: The Slack webhook URL must never be hardcoded into the application source code.
- **Gitignore Enforcement**: Local `.env` files are strictly added to `.gitignore` (already confirmed) to prevent accidental commits of local testing webhooks.
- **Kubernetes Secrets**: In production, the webhook URL will be managed as a Kubernetes `Secret`. The Helm chart's `values.yaml` will NOT contain the literal secret, but rather a reference.
- **Environment Variable Injection**: The Kubernetes Deployment will mount the `Secret` and inject it into the application container as the `SLACK_WEBHOOK_URL` environment variable.

## Consequences
- Maintains secure secret management practices.
- Decouples configuration from code.
