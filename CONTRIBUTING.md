# Contributing

Thanks for your interest in contributing.

This project is built with the [Atomic Spec](https://chappygo-os.github.io/Atomic-Spec/)
governance framework — features flow through specify → plan → tasks → implement.
See [CLAUDE.md](CLAUDE.md) for the full convention.

## Before opening a PR

1. Open an issue first for anything beyond a one-line fix.
2. Tests pass locally:
   - `cd backend && pytest --cov=src` (80% coverage gate, enforced in CI)
   - `cd frontend && pnpm test:unit && pnpm test:e2e`
3. No hardcoded secrets — use environment variables; document new vars in the
   relevant `.env.example`.
4. Validate user input at the boundary (Pydantic on the backend, Zod on the frontend).

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/): `feat`, `fix`,
`refactor`, `docs`, `test`, `chore`, `perf`, `ci`.

Example:

```
fix(sources): unify list-row DB strip with new lifecycle vocabulary
```

## Pull requests

- Target the `develop` branch (not `main`).
- Reference the issue: `Closes #123`.
- Keep PRs small and atomic.
