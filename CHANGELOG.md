# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

There are no tagged releases yet. Once the first version is tagged, prior
entries in `Unreleased` will be moved under that version with its release date.

## [Unreleased]

Initial public release preparation. High-level summary of what the platform
provides at this point:

### Added

- **Multi-node LangGraph agent pipeline** (v2 default, v1 retained as a rollback
  path) with eleven independently-configurable LLM stages — model, temperature,
  max-tokens, and prompt are set per stage from the admin UI.
- **Source connectors:** file upload (PDF / DOCX / XLSX / CSV / TXT / MD),
  single-page web URL (with SSRF guard), and SQL databases
  (PostgreSQL / MySQL / SQL Server), plus experimental MongoDB.
- **Natural-language → SQL** for database sources with `sqlglot` validation,
  read-only hardening, and automatic `LIMIT` injection.
- **Per-stage model resolution** against any OpenAI-compatible provider, with
  connector and provider credentials encrypted at rest (Fernet).
- **Streaming chat (SSE)** with inline numbered citations and a citation panel.
- **Embedder management** with a one-active-embedder invariant enforced by a
  partial unique index.
- **Langfuse observability** with per-node spans; degrades to a no-op when no
  keys are configured.
- **Admin console** (Next.js 15): sources, users and invitations, AI models,
  embedders, per-stage LLM settings, policy & guardrails, analytics, audit log.
- **Security hardening:** JWT access tokens with revocable database-stored
  refresh tokens, per-email account lockout, CSRF protection, CSP / HSTS /
  anti-clickjacking headers, and an SSRF guard on web fetches.
- **Docker Compose deployment** (nine services) with automatic database
  migrations on backend startup.

[Unreleased]: https://github.com/mohammad007kh/Internal-Knowledge-AI-Agent
