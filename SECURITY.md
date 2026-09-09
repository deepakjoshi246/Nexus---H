# Security

This MVP uses synthetic data only. Do not commit `.env`, credentials, production customer data, or database files. Configure secrets through environment variables and a secret manager in deployment. The deterministic guardrails must remain authoritative until model output has been independently validated. Add authentication, authorization, rate limiting, TLS, and structured secret redaction before production use. Handoff and audit identifiers are deterministic to prevent duplicate records, but SQLite is intended for single-process development deployments.
