# T-070 â€” LangGraph AgentState + Chat ORM + Pipeline Scaffold

**Status:** Done

## Context
```
Python 3.12 | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector
PostgreSQL 16 + pgvector Â· UUID PKs Â· soft-delete + audit columns
Alembic versioned migrations (down_revision chain: 0008 â†’ 0009)
LangGraph 8-node Â· interrupt() for clarification Â· SSE streaming
Langfuse self-hosted Â· every pipeline run must emit a trace
JWT 15-min access + 7-day rotating httpOnly refresh cookie Â· RBAC (admin/user)
snake_case vars/files/tables Â· PascalCase classes Â· SCREAMING_SNAKE_CASE constants
```

## Goal
Establish the **Phase 4 LangGraph foundation**:

1. `AgentState` TypedDict â€” shared state bag that flows through all 8 nodes  
2. `ChatSession` + `ChatMessage` ORM models  
3. Alembic migration `0009_chat.py`  
4. Empty `StateGraph` scaffold with 8 named node stubs  
5. DI container registrations for chat repositories  

No LLM calls yet â€” this task is pure wiring/scaffolding.

---

## Acceptance Criteria

- [ ] `AgentState` importable from `app.agent.state`
- [ ] `ChatSession` and `ChatMessage` ORM models importable from `app.models`
- [ ] Migration `0009` creates `chat_sessions` + `chat_messages` tables with correct FKs
- [ ] `StateGraph(AgentState)` compiles without error (smoke test)
- [ ] 8 stub nodes registered (`retrieve_context`, `generate_response`, `check_clarification`, `handle_clarification`, `format_response`, `save_message`, `load_history`, `route`)
- [ ] DI container has `chat_session_repository` + `chat_message_repository` Factories
- [ ] `requirements.txt` includes `langgraph>=0.1.0`

---

## 1  `app/agent/__init__.py`

```python
# app/agent/__init__.py
"""LangGraph pipeline package."""
```

---

## 2  `app/agent/state.py`

```python
# app/agent/state.py
"""AgentState â€” shared state bag for the LangGraph pipeline."""
from __future__ import annotations

from typing import Annotated, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """All data that flows between LangGraph nodes.

    Fields
    ------
    messages:
        Full conversation history (role + content).  ``add_messages``
        reducer appends rather than overwrites â€” never set this field
        directly, let LangGraph manage it.
    source_ids:
        Allowlist of source UUIDs the current user may access (FR-019).
        Populated by ``load_history`` node from the session's granted sources.
    retrieved_chunks:
        List of chunk dicts returned by the retrieval node.  Each dict
        has keys: ``chunk_id``, ``source_id``, ``text``, ``score``.
    requires_clarification:
        Set to ``True`` by the routing node when the query is ambiguous.
    clarification_question:
        The question text posed to the user when clarification is needed.
    session_id:
        UUID string of the active ``ChatSession``.
    user_id:
        UUID string of the authenticated user.
    trace_id:
        Langfuse trace ID for the current pipeline run.
    query:
        The raw user query text extracted from the latest human message.
    final_answer:
        Fully composed answer text, set by ``format_response`` node.
    error:
        Non-empty string if a node encountered a handled error.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    source_ids: list[str]
    retrieved_chunks: list[dict]
    requires_clarification: bool
    clarification_question: Optional[str]
    session_id: str
    user_id: str
    trace_id: str
    query: str
    final_answer: Optional[str]
    error: Optional[str]
```

---

## 3  `app/models/chat.py`

```python
# app/models/chat.py
"""Chat session and message ORM models."""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatSession(Base):
    """An ongoing dialogue between one user and the AI agent."""

    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
        default="New conversation",
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    is_deleted: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, default=False, index=True
    )

    messages: Mapped[list[ChatMessage]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
        lazy="raise",
    )


class ChatMessage(Base):
    """A single turn in a ``ChatSession``."""

    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    session_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[MessageRole] = mapped_column(
        sa.Enum(MessageRole, name="messagerole", create_type=False),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    session: Mapped[ChatSession] = relationship(
        "ChatSession", back_populates="messages"
    )
```

---

## 4  `app/models/__init__.py` â€” patch

Add to the existing `__init__.py` imports:

```python
from app.models.chat import ChatMessage, ChatSession, MessageRole  # noqa: F401
```

---

## 5  `alembic/versions/0009_chat.py`

```python
"""create chat tables

Revision ID: 00000000000009
Revises: 00000000000008
Create Date: 2025-01-15 14:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "00000000000009"
down_revision = "00000000000008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create messagerole enum
    op.execute("CREATE TYPE messagerole AS ENUM ('user', 'assistant', 'system')")

    op.create_table(
        "chat_sessions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("user_id", UUID(as_uuid=False), nullable=False),
        sa.Column("title", sa.Text, nullable=False, server_default="New conversation"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"])
    op.create_index("ix_chat_sessions_is_deleted", "chat_sessions", ["is_deleted"])

    op.create_table(
        "chat_messages",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("session_id", UUID(as_uuid=False), nullable=False),
        sa.Column(
            "role",
            sa.Enum("user", "assistant", "system", name="messagerole", create_type=False),
            nullable=False,
        ),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["chat_sessions.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"])


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.execute("DROP TYPE messagerole")
```

---

## 6  `app/agent/pipeline.py`

```python
# app/agent/pipeline.py
"""LangGraph StateGraph scaffold â€” 8-node pipeline.

Node stubs are empty coroutines that return an unchanged state dict.
Each node is replaced by its real implementation in subsequent tasks:
  - T-071  retrieve_context
  - T-072  generate_response
  - T-073  check_clarification, handle_clarification
  - T-074  format_response, save_message, load_history, route (full wiring)
"""
from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from app.agent.state import AgentState

logger = logging.getLogger(__name__)


# â”€â”€ Node stubs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


async def load_history(state: AgentState) -> dict:
    """Load conversation history from DB and populate state.messages."""
    logger.debug("node=load_history session=%s", state["session_id"])
    return {}


async def retrieve_context(state: AgentState) -> dict:
    """Semantic search over allowlisted sources and populate retrieved_chunks."""
    logger.debug("node=retrieve_context query=%s", state.get("query", ""))
    return {"retrieved_chunks": []}


async def check_clarification(state: AgentState) -> dict:
    """Decide whether the user query needs clarification."""
    logger.debug("node=check_clarification")
    return {"requires_clarification": False, "clarification_question": None}


async def handle_clarification(state: AgentState) -> dict:
    """Interrupt the graph and surface a clarification question to the user."""
    logger.debug("node=handle_clarification")
    return {}


async def generate_response(state: AgentState) -> dict:
    """Call LLM with retrieved context and produce a raw response."""
    logger.debug("node=generate_response")
    return {}


async def format_response(state: AgentState) -> dict:
    """Format the raw LLM response into the final answer."""
    logger.debug("node=format_response")
    return {}


async def save_message(state: AgentState) -> dict:
    """Persist the assistant message to the database."""
    logger.debug("node=save_message session=%s", state["session_id"])
    return {}


def route(state: AgentState) -> str:
    """Conditional edge: direct to handle_clarification or retrieve_context."""
    if state.get("requires_clarification"):
        return "handle_clarification"
    return "retrieve_context"


# â”€â”€ Graph assembly â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def build_pipeline() -> StateGraph:
    """Assemble the full 8-node LangGraph pipeline.

    Topology
    --------
    START â†’ load_history â†’ check_clarification
                                â†“ (route)
                    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                    â”‚ requires_clarification=True  â”‚
                    â”‚      handle_clarification    â”‚
                    â”‚             â†“                â”‚
                    â”‚           END                â”‚
                    â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                    â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
                    â”‚ normal path        â”‚
                    â”‚  retrieve_context  â”‚
                    â”‚  generate_response â”‚
                    â”‚  format_response   â”‚
                    â”‚  save_message      â”‚
                    â”‚       â†“           â”‚
                    â”‚      END          â”‚
                    â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
    """
    workflow = StateGraph(AgentState)

    # Register nodes
    workflow.add_node("load_history", load_history)
    workflow.add_node("check_clarification", check_clarification)
    workflow.add_node("handle_clarification", handle_clarification)
    workflow.add_node("retrieve_context", retrieve_context)
    workflow.add_node("generate_response", generate_response)
    workflow.add_node("format_response", format_response)
    workflow.add_node("save_message", save_message)

    # Edges
    workflow.add_edge(START, "load_history")
    workflow.add_edge("load_history", "check_clarification")
    workflow.add_conditional_edges(
        "check_clarification",
        route,
        {
            "handle_clarification": "handle_clarification",
            "retrieve_context": "retrieve_context",
        },
    )
    workflow.add_edge("handle_clarification", END)
    workflow.add_edge("retrieve_context", "generate_response")
    workflow.add_edge("generate_response", "format_response")
    workflow.add_edge("format_response", "save_message")
    workflow.add_edge("save_message", END)

    return workflow


# Singleton compiled graph (replaced in T-074 with MemorySaver checkpointer)
_graph = build_pipeline().compile()


def get_pipeline() -> StateGraph:
    """Return the compiled pipeline singleton."""
    return _graph
```

---

## 7  Chat Repositories â€” `app/repositories/chat_repository.py`

```python
# app/repositories/chat_repository.py
"""Chat session and message repositories."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.chat import ChatMessage, ChatSession, MessageRole
from app.repositories.base import BaseRepository


class ChatSessionRepository(BaseRepository[ChatSession]):
    model = ChatSession

    async def create(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        title: str = "New conversation",
    ) -> ChatSession:
        obj = ChatSession(user_id=user_id, title=title)
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    async def get(
        self, session: AsyncSession, *, session_id: str
    ) -> Optional[ChatSession]:
        result = await session.execute(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ChatSession]:
        result = await session.execute(
            select(ChatSession)
            .where(
                ChatSession.user_id == user_id,
                ChatSession.is_deleted.is_(False),
            )
            .order_by(ChatSession.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def soft_delete(self, session: AsyncSession, *, session_id: str) -> None:
        await session.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(is_deleted=True)
        )

    async def touch(self, session: AsyncSession, *, session_id: str) -> None:
        """Update updated_at to now."""
        await session.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(updated_at=datetime.now(timezone.utc))
        )


class ChatMessageRepository(BaseRepository[ChatMessage]):
    model = ChatMessage

    async def create(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        role: MessageRole,
        content: str,
    ) -> ChatMessage:
        msg = ChatMessage(session_id=session_id, role=role, content=content)
        session.add(msg)
        await session.flush()
        await session.refresh(msg)
        return msg

    async def list_for_session(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        limit: int = 100,
    ) -> list[ChatMessage]:
        result = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())
```

---

## 8  `containers.py` â€” patch

```python
# Inside ApplicationContainer class, after sync_job_service provider:

from app.repositories.chat_repository import (
    ChatMessageRepository,
    ChatSessionRepository,
)

chat_session_repository = providers.Factory(
    ChatSessionRepository,
    db_session=db_session,
)

chat_message_repository = providers.Factory(
    ChatMessageRepository,
    db_session=db_session,
)
```

---

## 9  `requirements.txt` â€” additions

```
langgraph>=0.1.0
langchain-core>=0.2.0
langchain-openai>=0.1.0
```

---

## Smoke Test

```python
# Paste into a Python REPL to confirm graph compiles:
from app.agent.pipeline import get_pipeline
g = get_pipeline()
assert g is not None
print("Pipeline compiled OK")
```

---

## Files Modified / Created

| Action | Path |
|---|---|
| CREATE | `app/agent/__init__.py` |
| CREATE | `app/agent/state.py` |
| CREATE | `app/models/chat.py` |
| PATCH  | `app/models/__init__.py` |
| CREATE | `alembic/versions/0009_chat.py` |
| CREATE | `app/agent/pipeline.py` |
| CREATE | `app/repositories/chat_repository.py` |
| PATCH  | `containers.py` |
| PATCH  | `requirements.txt` |
