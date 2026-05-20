# Security Policy

Internal Knowledge AI Agent sits between users and internal data, so security
reports are taken seriously. This document explains what is supported, how to
report a vulnerability privately, and what to expect afterwards.

## Supported versions

This project is pre-1.0 and ships without numbered releases yet. Only the latest
code on the default branches is supported:

| Version            | Supported          |
| ------------------ | ------------------ |
| Latest `main`      | Yes                |
| Latest `develop`   | Yes                |
| Older commits/tags | No                 |

Once versioned releases are tagged, this table will be updated to list the
supported release lines.

## Reporting a vulnerability

**Please do not open a public GitHub issue, pull request, or discussion for a
security vulnerability.** Public disclosure before a fix is available puts every
deployment at risk.

Report privately through GitHub's built-in private vulnerability reporting:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability** (GitHub Security Advisories).
3. Provide as much detail as you can (see below).

> Maintainer note: if you prefer to also offer an email channel, add a contact
> address here. No contact email is published by default — GitHub's private
> advisory flow is the canonical channel.

A useful report includes:

- A clear description of the issue and its security impact.
- Steps to reproduce, or a proof of concept.
- Affected component (e.g. auth, connectors, NL→SQL, web fetch) and, if known,
  the relevant file(s) or endpoint(s).
- The commit hash or branch you tested against.
- Any suggested remediation, if you have one.

## What to expect

This is a personal, solo-maintained open-source project, not a commercial
product with a staffed security team. Handling is best-effort:

- **Acknowledgement:** typically within a few days.
- **Assessment and updates:** as the maintainer's availability allows; you will
  be kept informed of progress.
- **Fix and disclosure:** once a fix is ready, a patch is merged to the default
  branch and the advisory is published. With your consent, you will be credited.

No formal SLA or guaranteed response window is offered. Please report in good
faith and allow reasonable time for a fix before any public disclosure.

## Scope

**In scope** — vulnerabilities in this repository's own code, for example:

- Authentication and session handling (JWT issuance, refresh-token revocation,
  account lockout, password reset).
- Authorization / access-control gaps between users and admin functionality.
- Injection in the NL→SQL path or other generated queries.
- Server-side request forgery (SSRF) via the web-fetch connector.
- Cross-site scripting (XSS), CSRF, or insecure handling of stored secrets.
- Leakage of connector credentials, tokens, or other sensitive data.

**Out of scope:**

- Vulnerabilities in third-party dependencies — please report those upstream.
  (You may still flag them here so the dependency can be bumped.)
- Issues caused by self-hosting misconfiguration: weak or default secrets,
  exposing internal services to the public internet, disabling the shipped
  guards, running without TLS in front of the stack, etc.
- Findings that require already-compromised infrastructure or a malicious admin
  account (admins are trusted by design).
- Volumetric denial-of-service and automated scanner output without a concrete,
  demonstrated impact.

## Existing security measures (threat model context)

The application already ships with the following controls. Understanding them
helps frame what a meaningful report looks like:

- **Authentication:** JWT access tokens paired with opaque, database-stored
  refresh tokens that can be revoked server-side.
- **Brute-force resistance:** per-email account lockout (Redis) layered on top of
  per-IP rate limiting.
- **CSRF protection:** double-submit cookie pattern on state-changing requests.
- **Browser hardening:** CSP, anti-clickjacking, and (production-gated) HSTS
  response headers.
- **SSRF guard:** the single-page web-fetch connector blocks RFC1918, loopback,
  link-local, and cloud-metadata addresses, and enforces robots and size caps.
- **NL→SQL hardening:** generated SQL is validated with `sqlglot`, restricted to
  read-only operations, and given an automatic `LIMIT` before it touches any
  connected database.
- **Secrets at rest:** connector credentials and provider keys are encrypted with
  Fernet; all secrets are supplied via environment variables, never hardcoded.

Reports that bypass or weaken any of these controls are especially valuable.

Thank you for helping keep the project and its users safe.
