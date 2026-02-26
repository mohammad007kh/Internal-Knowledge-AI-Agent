---
id: T-007
title: GitHub Actions CI Pipeline — Lint, Test, Build Gate
status: Not Started
created: 2026-02-25
phase: Phase 0 — Foundation
user_story: cross
requirements: []
priority: P1
depends_on: [T-001, T-002, T-005, T-006]
---

## 📋 Embedded Context

**Stack**: Python 3.12 + FastAPI · Next.js 15 App Router · PostgreSQL 16 + pgvector · Docker Compose · pytest + Playwright  
**Conventions**: Conventional commits · NNN-description branches · RFC 7807 errors · ≥80% coverage gate  
**Key rule**: CI must fail fast on lint → test → build order; never push broken code to `main`

---

## 🎯 Objective

Create a GitHub Actions workflow that runs on every push and PR: lints backend (ruff + mypy) and frontend (biome + tsc), runs pytest with coverage gate, and verifies Docker Compose builds cleanly. The workflow blocks merges with non-zero exit codes.

---

## 🛠️ Files to Create

| Path | Purpose |
|------|---------|
| `.github/workflows/ci.yml` | Main CI workflow: lint → test → build |
| `.github/workflows/pr-checks.yml` | PR title format check (conventional commits) |

---

## Implementation

**`.github/workflows/ci.yml`:**
```yaml
name: CI

on:
  push:
    branches: [main, "001-*"]
  pull_request:
    branches: [main]

jobs:
  lint-backend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: ./backend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install ruff mypy
      - run: ruff check src/ tests/
      - run: mypy src/ --ignore-missing-imports

  lint-frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: ./frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20" }
      - run: npm ci
      - run: npx tsc --noEmit
      - run: npx biome check .

  test-backend:
    runs-on: ubuntu-latest
    needs: lint-backend
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env:
          POSTGRES_DB: test_db
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
        ports: ["5432:5432"]
        options: --health-cmd="pg_isready" --health-interval=10s
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
        options: --health-cmd="redis-cli ping"
    env:
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/test_db
      REDIS_URL: redis://localhost:6379/0
      JWT_SECRET_KEY: test-secret-key-256bits-for-ci-only
      JWT_REFRESH_SECRET_KEY: test-refresh-secret-key-256bits-for-ci
      BOOTSTRAP_ADMIN_EMAIL: admin@test.com
      BOOTSTRAP_ADMIN_PASSWORD: AdminTest123!
      ENCRYPTION_KEY: ${{ secrets.TEST_ENCRYPTION_KEY || 'dGVzdC1rZXktMTYtYnl0ZXMtZm9yY2k=' }}
      MINIO_ENDPOINT: localhost:9000
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
    defaults:
      run:
        working-directory: ./backend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[test]"
      - run: alembic upgrade head
      - run: |
          pytest tests/ \
            --cov=src \
            --cov-report=xml \
            --cov-fail-under=80 \
            -q
      - uses: codecov/codecov-action@v4
        with:
          files: ./backend/coverage.xml

  build:
    runs-on: ubuntu-latest
    needs: [lint-frontend, test-backend]
    steps:
      - uses: actions/checkout@v4
      - run: docker compose build --no-cache
```

**`.github/workflows/pr-checks.yml`:**
```yaml
name: PR Checks

on:
  pull_request:
    types: [opened, edited, synchronize]

jobs:
  title-format:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Validate PR title (conventional commits)
        run: |
          TITLE="${{ github.event.pull_request.title }}"
          echo "PR title: $TITLE"
          echo "$TITLE" | grep -qE '^(feat|fix|chore|docs|test|refactor|style|ci)\(.+\): .+' \
            && echo "Title OK" \
            || (echo "ERROR: PR title must match: type(scope): description" && exit 1)
```

---

## 🔌 Wiring Checklist

- [ ] `ci.yml` has postgres + redis service containers with healthchecks
- [ ] pytest coverage gate set to `--cov-fail-under=80`
- [ ] `lint-backend` and `lint-frontend` run before `test-backend`
- [ ] `build` job only runs after both lint and test pass
- [ ] PR title check enforces conventional commit format

---

## ✅ Verification

Push a branch with a test commit; verify in GitHub Actions that all 4 jobs appear and the `build` job only starts after `test-backend` passes. Push a PR with a badly formatted title; verify `title-format` fails.

---

## 📝 Completion Log

- [ ] Code implemented
- [ ] Tests passed
- [ ] Linter passed
- [ ] Wiring verified
- [ ] Integration verification passed
