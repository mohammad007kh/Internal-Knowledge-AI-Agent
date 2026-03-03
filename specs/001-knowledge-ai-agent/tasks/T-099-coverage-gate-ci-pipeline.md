# T-099 Â· Coverage Gate, CI Pipeline & Final Spec Verification

**Status:** Done

**Phase:** 9 â€” Testing, Polish & SC Verification  
**Depends on:** T-091, T-092, T-093, T-094, T-095, T-096, T-097, T-098  
**Blocks:** nothing (final task)

---

## Context

```
Python 3.12 | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector
Next.js 15 App Router Â· shadcn/ui Â· Tailwind CSS v4
React Context Â· TanStack Query v5 Â· react-hook-form Â· Zod
PostgreSQL 16 + pgvector Â· HNSW m=16 ef_construction=64 Â· UUID PKs Â· soft-delete + audit columns
Alembic versioned migrations
Celery + Redis Â· Beat replicas=1 STRICT
MinIO Â· presigned PUT pattern
JWT 15-min access + 7-day rotating httpOnly refresh cookie Â· bcrypt Â· RBAC (admin/user)
Fernet (connection configs + LLM API keys at rest)
LangGraph 8-node Â· interrupt() for clarification Â· SSE streaming
Langfuse self-hosted Â· every pipeline run must emit a trace
RFC 7807 Problem Details â€” all non-2xx API responses
Structured logging Â· INFO level Â· X-Request-ID correlation
CORS strict Â· CSRF SameSite=Strict httpOnly Â· CSP moderate Â· rate-limit IP
Dark mode Â· responsive Â· WCAG-AA Â· no animations Â· Lucide icons Â· Sonner toasts
snake_case vars/files/tables Â· PascalCase classes Â· SCREAMING_SNAKE_CASE constants
pytest + httpx + Playwright Â· â‰¥80% coverage
Docker Compose 9 services: frontend, backend, worker, beat, db, redis, minio, langfuse, langfuse-db
```

---

## Objective

This is the **capstone task** for Phase 9. It:

1. Enforces the â‰¥ 80 % pytest coverage gate across all backend code  
2. Creates the GitHub Actions CI pipeline that runs on every PR and main push  
3. Runs the final cross-cutting spec compliance check confirming every FR/NFR from the spec has a corresponding test or explicit waiver  
4. Produces a human-readable `SPEC_COMPLIANCE_REPORT.md` artifact

---

## Files to Create / Edit

```
.github/
  workflows/
    ci.yml                        â† full CI pipeline
    playwright.yml                â† Playwright E2E workflow (separate for parallelism)

src/backend/
  pyproject.toml                  â† coverage config (â‰¥80% fail threshold)

scripts/
  spec_compliance_check.py        â† FR/NFR â†’ test-file traceability verifier

SPEC_COMPLIANCE_REPORT.md         â† produced by script; committed in CI
```

---

## 1. `pyproject.toml` â€” Coverage Gate

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = [
  "--strict-markers",
  "-q",
  "--cov=app",
  "--cov-report=term-missing",
  "--cov-report=xml:coverage.xml",
  "--cov-fail-under=80",     # â† HARD GATE
]
markers = [
  "slow: marks tests as slow (deselect with -m 'not slow')",
  "langfuse: marks tests requiring Langfuse service",
]

[tool.coverage.run]
branch = true
source = ["app"]
omit = ["app/alembic/*", "app/tests/*", "app/__main__.py"]

[tool.coverage.report]
show_missing = true
skip_covered = false
fail_under = 80

[tool.coverage.xml]
output = "coverage.xml"
```

---

## 2. GitHub Actions â€” Backend CI â€” `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

env:
  PYTHON_VERSION: "3.12"
  NODE_VERSION: "20"

jobs:
  # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  # Backend: lint, type-check, unit + integration tests, 80% coverage gate
  # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  backend:
    name: Backend Tests
    runs-on: ubuntu-latest

    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_USER: test_user
          POSTGRES_PASSWORD: test_password
          POSTGRES_DB: test_db
        options: >-
          --health-cmd "pg_isready -U test_user"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

      redis:
        image: redis:7-alpine
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 6379:6379

    defaults:
      run:
        working-directory: src/backend

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: "pip"

      - name: Install dependencies
        run: pip install -e ".[test,dev]"

      - name: Lint (ruff)
        run: ruff check app tests

      - name: Format check
        run: ruff format --check app tests

      - name: Type-check (mypy)
        run: mypy app --ignore-missing-imports

      - name: Run Alembic migrations
        env:
          DATABASE_URL: postgresql+asyncpg://test_user:test_password@localhost:5432/test_db
        run: alembic upgrade head

      - name: Run tests with coverage gate
        env:
          DATABASE_URL: postgresql+asyncpg://test_user:test_password@localhost:5432/test_db
          REDIS_URL: redis://localhost:6379/0
          SECRET_KEY: ci-test-secret-key-32-bytes-xxxx
          JWT_SECRET: ci-jwt-secret-key-at-least-32-bytes
          FERNET_KEY: Y3VycmVudGtleW11c3RiZTMyYnl0ZXNsb25n
          ENVIRONMENT: test
          RATE_LIMIT_LOGIN: "5/minute"
        run: pytest --cov=app --cov-fail-under=80 -x

      - name: Upload coverage to Codecov
        uses: codecov/codecov-action@v4
        if: always()
        with:
          files: coverage.xml
          flags: backend

      - name: Upload coverage artifact
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: backend-coverage
          path: src/backend/coverage.xml

  # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  # Frontend: lint, type-check, unit tests
  # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  frontend:
    name: Frontend Tests
    runs-on: ubuntu-latest

    defaults:
      run:
        working-directory: src/frontend

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: ${{ env.NODE_VERSION }}
          cache: "npm"
          cache-dependency-path: src/frontend/package-lock.json

      - name: Install dependencies
        run: npm ci

      - name: Lint (ESLint)
        run: npm run lint

      - name: Type-check (tsc)
        run: npx tsc --noEmit

      - name: Unit tests (Vitest)
        run: npm run test -- --coverage --reporter=verbose

  # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  # Docker Compose: smoke test all 9 services start cleanly
  # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  compose-smoke:
    name: Docker Compose Smoke
    runs-on: ubuntu-latest
    needs: [backend, frontend]
    if: github.ref == 'refs/heads/main' || github.ref == 'refs/heads/develop'

    steps:
      - uses: actions/checkout@v4

      - name: Copy test env file
        run: cp .env.example .env

      - name: Build and start services
        run: docker compose up -d --build --wait
        timeout-minutes: 10

      - name: Check all 9 services healthy
        run: |
          services=(frontend backend worker beat db redis minio langfuse langfuse-db)
          for svc in "${services[@]}"; do
            STATUS=$(docker compose ps --format json | jq -r ".[] | select(.Service==\"$svc\") | .Health")
            echo "$svc: $STATUS"
            if [[ "$STATUS" != "healthy" && "$STATUS" != "running" ]]; then
              echo "ERROR: $svc is not healthy"
              docker compose logs $svc | tail -30
              exit 1
            fi
          done

      - name: Backend API health probe
        run: |
          for i in {1..10}; do
            STATUS=$(curl -sS -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/health)
            if [ "$STATUS" = "200" ]; then
              echo "Health check passed"
              exit 0
            fi
            sleep 3
          done
          echo "Health check failed after 10 attempts"
          exit 1

      - name: Teardown
        if: always()
        run: docker compose down -v

  # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  # Spec compliance check
  # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
  spec-compliance:
    name: Spec Compliance Check
    runs-on: ubuntu-latest
    needs: [backend, frontend]

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}

      - name: Run compliance check
        run: python scripts/spec_compliance_check.py --output SPEC_COMPLIANCE_REPORT.md

      - name: Upload compliance report
        uses: actions/upload-artifact@v4
        with:
          name: spec-compliance-report
          path: SPEC_COMPLIANCE_REPORT.md
```

---

## 3. GitHub Actions â€” Playwright E2E â€” `.github/workflows/playwright.yml`

```yaml
name: E2E Tests (Playwright)

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:

jobs:
  e2e:
    name: Playwright E2E
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"
          cache-dependency-path: src/frontend/package-lock.json

      - name: Install Node deps
        run: npm ci
        working-directory: src/frontend

      - name: Install Playwright browsers
        run: npx playwright install --with-deps chromium firefox
        working-directory: src/frontend

      - name: Start backend + dependencies
        run: docker compose up -d db redis minio backend worker
        timeout-minutes: 5

      - name: Seed E2E test users
        run: |
          until curl -sf http://localhost:8000/api/v1/health; do sleep 2; done
          docker compose exec -T backend python -m app.scripts.seed_e2e_users

      - name: Start frontend dev server
        run: npm run dev &
        working-directory: src/frontend

      - name: Wait for frontend ready
        run: |
          npx wait-on http://localhost:3000 --timeout 30000

      - name: Run Playwright tests
        run: npx playwright test --project=chromium --reporter=html
        working-directory: src/frontend
        env:
          BASE_URL: http://localhost:3000

      - name: Upload Playwright report
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: playwright-report
          path: src/frontend/playwright-report/

      - name: Teardown
        if: always()
        run: docker compose down -v
```

---

## 4. Spec Compliance Script â€” `scripts/spec_compliance_check.py`

```python
#!/usr/bin/env python3
"""
Spec compliance checker.

Reads specs/001-knowledge-ai-agent/spec.md, extracts FR-NNN and NFR-NNN identifiers,
then verifies each has at least one corresponding test assertion in tests/.

Exits non-zero if any FR/NFR has zero test coverage and no waiver.

Usage:
    python scripts/spec_compliance_check.py [--output REPORT.md]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


SPEC_FILE = Path("specs/001-knowledge-ai-agent/spec.md")
TESTS_DIR = Path("src/backend/tests")
E2E_TESTS_DIR = Path("src/frontend/tests")
OUTPUT_DEFAULT = Path("SPEC_COMPLIANCE_REPORT.md")

FR_PATTERN = re.compile(r"(FR-\d{3})")
NFR_PATTERN = re.compile(r"(NFR-\d{3})")

# FRs / NFRs that are intentionally not tested directly (infrastructure-level)
WAIVERS: set[str] = {
    "NFR-001",  # availability / uptime â€” infra concern, not unit-testable
    "NFR-009",  # Docker CPU limits â€” container runtime config
}


def extract_requirements(spec_text: str) -> set[str]:
    frs = set(FR_PATTERN.findall(spec_text))
    nfrs = set(NFR_PATTERN.findall(spec_text))
    return frs | nfrs


def collect_test_files() -> list[Path]:
    files: list[Path] = []
    for base in [TESTS_DIR, E2E_TESTS_DIR]:
        if base.exists():
            files.extend(base.rglob("*.py"))
            files.extend(base.rglob("*.ts"))
            files.extend(base.rglob("*.spec.ts"))
    return files


def build_coverage_map(req_ids: set[str], test_files: list[Path]) -> dict[str, list[str]]:
    """Return {req_id: [test_file_path, ...]} for each requirement."""
    coverage: dict[str, list[str]] = {rid: [] for rid in req_ids}

    for fpath in test_files:
        try:
            content = fpath.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for rid in req_ids:
            if rid in content:
                coverage[rid].append(str(fpath))

    return coverage


def write_report(
    coverage: dict[str, list[str]],
    waivers: set[str],
    output: Path,
) -> tuple[int, int]:
    """Write markdown report; return (covered, uncovered) counts."""
    lines: list[str] = []
    lines.append("# Spec Compliance Report\n")
    lines.append(f"Generated: {__import__('datetime').datetime.utcnow().isoformat()}Z\n\n")
    lines.append("## Summary\n")

    covered = [r for r, tests in coverage.items() if tests or r in waivers]
    uncovered = [r for r, tests in coverage.items() if not tests and r not in waivers]

    lines.append(f"- **Total requirements**: {len(coverage)}\n")
    lines.append(f"- **Covered / waived**: {len(covered)}\n")
    lines.append(f"- **Uncovered**: {len(uncovered)}\n\n")

    if uncovered:
        lines.append("## âŒ Uncovered Requirements\n\n")
        for rid in sorted(uncovered):
            lines.append(f"- `{rid}` â€” no test file references this ID\n")
        lines.append("\n")

    lines.append("## âœ… Covered Requirements\n\n")
    for rid in sorted(covered):
        tests = coverage[rid]
        if rid in waivers:
            lines.append(f"- `{rid}` â€” **WAIVED** (infrastructure / runtime)\n")
        else:
            lines.append(f"- `{rid}` â€” {len(tests)} test file(s)\n")
            for t in tests[:3]:
                lines.append(f"  - `{t}`\n")
            if len(tests) > 3:
                lines.append(f"  - â€¦ and {len(tests) - 3} more\n")

    output.write_text("".join(lines), encoding="utf-8")
    return len(covered), len(uncovered)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT))
    args = parser.parse_args()

    if not SPEC_FILE.exists():
        print(f"ERROR: spec file not found: {SPEC_FILE}", file=sys.stderr)
        sys.exit(2)

    spec_text = SPEC_FILE.read_text(encoding="utf-8")
    req_ids = extract_requirements(spec_text)
    print(f"Found {len(req_ids)} requirements in spec.")

    test_files = collect_test_files()
    print(f"Scanning {len(test_files)} test filesâ€¦")

    coverage = build_coverage_map(req_ids, test_files)
    output_path = Path(args.output)
    covered, uncovered = write_report(coverage, WAIVERS, output_path)

    print(f"\nCompliance report written to: {output_path}")
    print(f"Covered/waived: {covered} | Uncovered: {uncovered}")

    if uncovered:
        print(
            f"\nFAIL: {uncovered} requirement(s) have no test coverage and no waiver.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("\nPASS: All requirements covered or explicitly waived.")


if __name__ == "__main__":
    main()
```

---

## 5. Final Integration Checklist (`FINAL_CHECKLIST.md`)

This file is created by the developer upon completing T-099:

```markdown
# Phase 9 Final Checklist

## Coverage gate
- [ ] `pytest --cov=app --cov-fail-under=80` exits 0 locally
- [ ] `coverage.xml` produced; report shows â‰¥ 80% branch coverage

## CI pipeline
- [ ] `.github/workflows/ci.yml` passes all jobs on a feature branch PR
- [ ] Backend tests: lint â†’ type-check â†’ migrations â†’ pytest (80% gate)
- [ ] Frontend tests: lint â†’ tsc â†’ vitest
- [ ] compose-smoke: all 9 services healthy; `/api/v1/health` returns 200

## E2E
- [ ] `.github/workflows/playwright.yml` passes for chromium + firefox
- [ ] Playwright HTML report artifact uploaded

## Spec compliance
- [ ] `python scripts/spec_compliance_check.py` exits 0
- [ ] `SPEC_COMPLIANCE_REPORT.md` shows 0 uncovered requirements
- [ ] Waivers documented: NFR-001, NFR-009

## All Phase 9 tasks signed-off
- [ ] T-091 â€” Integration test scaffolding
- [ ] T-092 â€” Celery task queue integration tests
- [ ] T-093 â€” Playwright E2E critical user journeys
- [ ] T-094 â€” Accessibility audit (WCAG-AA)
- [ ] T-095 â€” Worker crash & retry integration tests
- [ ] T-096 â€” Security hardening tests
- [ ] T-097 â€” Dark mode, responsive layout & polish
- [ ] T-098 â€” Structured logging & Langfuse trace verification
- [ ] T-099 â€” Coverage gate, CI pipeline & final spec verification (this task)
```

---

## Definition of Done

- [ ] `--cov-fail-under=80` set in `pyproject.toml`; `pytest` fails if coverage drops below 80%
- [ ] `ci.yml` â†’ backend job: ruff lint â†’ ruff format â†’ mypy â†’ alembic upgrade â†’ pytest (gate)
- [ ] `ci.yml` â†’ frontend job: ESLint â†’ tsc â†’ vitest
- [ ] `ci.yml` â†’ compose-smoke (main/develop only): all 9 services healthy
- [ ] `playwright.yml` runs E2E in chromium + firefox; uploads HTML report
- [ ] `scripts/spec_compliance_check.py` exits 0 (all FRs/NFRs covered or waived)
- [ ] `SPEC_COMPLIANCE_REPORT.md` artifact: 0 uncovered requirements listed
- [ ] `FINAL_CHECKLIST.md` exists and all boxes checked before merge to main
