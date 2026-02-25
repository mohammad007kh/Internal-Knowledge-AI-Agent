# Copilot Skills Index — Internal Knowledge AI Agent

All skill files live in `.github/skills/`. They are auto-loaded by Copilot via `.vscode/settings.json`.
To add a new skill: copy the `SKILL.md` to `.github/skills/<name>.md`, then add the file reference to `.vscode/settings.json`.

---

## Index

### Backend — Python / FastAPI
| Skill | File | Use when… |
|---|---|---|
| FastAPI Pro | `.github/skills/fastapi-pro.md` | Building any FastAPI endpoint, middleware, lifespan, DI wiring |
| FastAPI Router | `.github/skills/fastapi-router-py.md` | Structuring routers, prefixes, dependencies per domain |
| FastAPI Templates | `.github/skills/fastapi-templates.md` | Boilerplate for new FastAPI services |
| Python Pro | `.github/skills/python-pro.md` | General Python 3.12+ idioms, typing, dataclasses |
| Python Patterns | `.github/skills/python-patterns.md` | Design patterns applied in Python |
| Async Python | `.github/skills/async-python-patterns.md` | `asyncio`, `async`/`await`, background tasks, Celery async |
| Pydantic Models | `.github/skills/pydantic-models-py.md` | Request/response schemas, validators, settings |
| Python Testing | `.github/skills/python-testing-patterns.md` | `pytest`, fixtures, mocks, async test patterns |
| Python Performance | `.github/skills/python-performance-optimization.md` | Profiling, query batching, caching patterns |

### Database
| Skill | File | Use when… |
|---|---|---|
| PostgreSQL | `.github/skills/postgresql.md` | Writing or reviewing SQL for PostgreSQL 16 |
| Postgres Best Practices | `.github/skills/postgres-best-practices.md` | Indexes, vacuum, connection pooling (pgbouncer) |
| Database Design | `.github/skills/database-design.md` | Schema design, normalisation, constraints |
| Database Architect | `.github/skills/database-architect.md` | High-level DB architecture decisions |
| SQL Migrations | `.github/skills/database-migrations-sql-migrations.md` | Alembic migration scripts |
| SQL Optimisation | `.github/skills/sql-optimization-patterns.md` | Query plans, EXPLAIN ANALYZE, index hints |
| SQL Pro | `.github/skills/sql-pro.md` | Complex queries, CTEs, window functions |
| NoSQL Expert | `.github/skills/nosql-expert.md` | MongoDB connector design, aggregation pipelines |

### AI / RAG / LLM
| Skill | File | Use when… |
|---|---|---|
| LangChain Architecture | `.github/skills/langchain-architecture.md` | Chains, tools, retrievers, memory design |
| LangGraph | `.github/skills/langgraph.md` | 8-node pipeline, `interrupt()`, state graph |
| Langfuse | `.github/skills/langfuse.md` | Tracing integration, span creation, scoring |
| RAG Engineer | `.github/skills/rag-engineer.md` | End-to-end RAG system design |
| RAG Implementation | `.github/skills/rag-implementation.md` | Chunking, embedding, retrieval implementation |
| LLM App Patterns | `.github/skills/llm-app-patterns.md` | Prompt templates, output parsers, retry logic |
| LangChain Agent Dev | `.github/skills/llm-application-dev-langchain-agent.md` | Building tool-calling agents |
| Embedding Strategies | `.github/skills/embedding-strategies.md` | Embedding models, batch processing, normalisation |
| Vector DB Engineer | `.github/skills/vector-database-engineer.md` | pgvector design, HNSW config (m=16, ef=64) |
| Vector Index Tuning | `.github/skills/vector-index-tuning.md` | HNSW/IVFFlat tuning, ef_search, probes |
| Hybrid Search | `.github/skills/hybrid-search-implementation.md` | BM25 + semantic fusion, RRF scoring |
| Similarity Search | `.github/skills/similarity-search-patterns.md` | Cosine similarity, MMR, reranking |
| Multi-Agent Patterns | `.github/skills/multi-agent-patterns.md` | Agent-to-agent delegation, orchestration |
| Agent Evaluation | `.github/skills/agent-evaluation.md` | Evaluating agent quality, traces, metrics |
| LLM Evaluation | `.github/skills/llm-evaluation.md` | Response quality metrics, benchmarking |

### Frontend — Next.js / React / TypeScript / Tailwind
| Skill | File | Use when… |
|---|---|---|
| Next.js App Router | `.github/skills/nextjs-app-router-patterns.md` | App Router layouts, RSC, route handlers |
| Next.js Best Practices | `.github/skills/nextjs-best-practices.md` | Data fetching, caching, metadata, image opt |
| React Best Practices | `.github/skills/react-best-practices.md` | Hooks, composition, performance, memo |
| React Patterns | `.github/skills/react-patterns.md` | HOC, render props, compound components |
| React State Management | `.github/skills/react-state-management.md` | TanStack Query, React Context, Zustand |
| TypeScript Pro | `.github/skills/typescript-pro.md` | Advanced types, generics, utility types |
| TypeScript Expert | `.github/skills/typescript-expert.md` | Strict mode, type narrowing, declaration files |
| Tailwind Patterns | `.github/skills/tailwind-patterns.md` | Class composition, responsive, dark mode |
| Tailwind Design System | `.github/skills/tailwind-design-system.md` | Design tokens, shadcn/ui integration |
| WCAG Audit Patterns | `.github/skills/wcag-audit-patterns.md` | WCAG-AA compliance, aria, keyboard nav |

### Infrastructure / DevOps
| Skill | File | Use when… |
|---|---|---|
| Docker Expert | `.github/skills/docker-expert.md` | Docker Compose 9-service setup, healthchecks |
| API Design Principles | `.github/skills/api-design-principles.md` | REST conventions, versioning, pagination |
| API Patterns | `.github/skills/api-patterns.md` | Error formats (RFC 7807), idempotency, rate-limiting |
| OpenAPI Spec | `.github/skills/openapi-spec-generation.md` | Writing/reviewing OpenAPI 3.1 contract files |
| File Uploads | `.github/skills/file-uploads.md` | MinIO presigned PUT URL pattern |

### Auth / Security
| Skill | File | Use when… |
|---|---|---|
| Auth Implementation | `.github/skills/auth-implementation-patterns.md` | JWT (15m) + httpOnly refresh cookie (7d), bcrypt |
| API Security | `.github/skills/api-security-best-practices.md` | Input sanitisation, rate limiting, CORS, headers |
| Security Hardening | `.github/skills/security-scanning-security-hardening.md` | Dependency scanning, secrets detection |

### Architecture / Code Quality
| Skill | File | Use when… |
|---|---|---|
| Clean Code | `.github/skills/clean-code.md` | Naming, SRP, function size, readability |
| Architecture Patterns | `.github/skills/architecture-patterns.md` | Clean architecture, layering, DI container |
| Backend Dev Guidelines | `.github/skills/backend-dev-guidelines.md` | Backend coding standards for this project |
| Frontend Dev Guidelines | `.github/skills/frontend-dev-guidelines.md` | Frontend coding standards for this project |
| Backend Architect | `.github/skills/backend-architect.md` | High-level backend design decisions |
| Senior Full-Stack | `.github/skills/senior-fullstack.md` | Cross-cutting concerns, tradeoff analysis |
| TDD Workflow | `.github/skills/tdd-workflow.md` | Red-green-refactor cycle, test-first approach |
| Code Review Excellence | `.github/skills/code-review-excellence.md` | Code review checklist and review comments |
| Error Handling Patterns | `.github/skills/error-handling-patterns.md` | Exception hierarchy, structured error responses |
| Debugging Strategies | `.github/skills/debugging-strategies.md` | Systematic debugging, logging, tracing |
| Architect Review | `.github/skills/architect-review.md` | Architecture review checklist |
