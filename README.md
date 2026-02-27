# Internal Knowledge AI Agent

An AI-powered knowledge retrieval and question answering system that indexes internal
documents and surfaces relevant answers through a conversational interface.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend API | Python 3.12 + FastAPI |
| Agent Pipeline | LangChain + LangGraph (8-node) |
| Frontend | Next.js 15 (App Router) + shadcn/ui + Tailwind CSS v4 |
| Database | PostgreSQL 16 + pgvector |
| Jobs | Celery + Redis |
| Observability | Langfuse (self-hosted) |
| Object Storage | MinIO |
| Deployment | Docker Compose (9 services) |

## Prerequisites

- Docker ≥ 24.x and Docker Compose ≥ 2.24.x
- Python 3.12 (for local backend development)
- Node.js 20+ (for local frontend development)

## Quick Start

### 1. Clone and configure environment

```bash
git clone <repo-url>
cd "Internal Knowledge AI Agent"
cp .env.example .env
# Edit .env and fill in all required values
```

### 2. Start all services

```bash
docker compose up -d
```

Services start at:
- **Frontend**: http://localhost:3001
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Langfuse**: http://localhost:3000
- **MinIO Console**: http://localhost:9001

### 3. Run database migrations

```bash
docker compose exec backend alembic upgrade head
```

## Local Development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn src.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Running Tests

### Backend

```bash
cd backend
pytest                         # all tests
pytest tests/unit              # unit tests only
pytest tests/integration       # integration tests only
pytest --cov=src --cov-report=html   # with coverage
```

### Frontend (E2E)

```bash
cd frontend
npx playwright test
```

## Project Structure

```
.
├── backend/
│   ├── src/
│   │   ├── api/           # FastAPI routers
│   │   ├── core/          # App factory, lifespan, DI container
│   │   ├── models/        # SQLAlchemy ORM models
│   │   ├── repositories/  # Data access layer (Repository pattern)
│   │   ├── services/      # Business logic
│   │   ├── workers/       # Celery tasks
│   │   └── config/        # Configuration (app_config.yaml)
│   ├── tests/
│   │   ├── unit/
│   │   └── integration/
│   ├── alembic/           # Database migrations
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   └── app/           # Next.js App Router pages
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   └── package.json
├── docker-compose.yml
├── .env.example
└── README.md
```

## Environment Variables

See [.env.example](.env.example) for all required configuration.

Key variables:

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string |
| `JWT_SECRET_KEY` | 256-bit JWT signing key |
| `ENCRYPTION_KEY` | Fernet key for connector config encryption |
| `LANGFUSE_*` | Langfuse observability credentials |

## Contributing

Commits follow [Conventional Commits](https://www.conventionalcommits.org/):
`feat:` `fix:` `chore:` `docs:` `test:` `refactor:`

## License

Internal use only.
