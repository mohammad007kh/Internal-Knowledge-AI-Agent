"""Shared fixtures for pipeline integration tests."""
from __future__ import annotations

import uuid

import pytest
from langchain_core.messages import HumanMessage
from unittest.mock import AsyncMock, MagicMock

from src.agent.state import AgentState


@pytest.fixture
def session_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def user_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def source_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def base_state(session_id: str, user_id: str, source_id: str) -> AgentState:
    return {
        "messages": [HumanMessage(content="What is our parental leave policy?")],
        "source_ids": [source_id],
        "retrieved_chunks": [],
        "requires_clarification": False,
        "clarification_question": None,
        "session_id": session_id,
        "user_id": user_id,
        "trace_id": str(uuid.uuid4()),
        "query": "What is our parental leave policy?",
        "final_answer": None,
        "error": None,
    }


@pytest.fixture
def mock_langfuse() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_chunk_repository() -> AsyncMock:
    repo = AsyncMock()
    repo.similarity_search.return_value = [
        {
            "chunk_id": str(uuid.uuid4()),
            "source_id": str(uuid.uuid4()),
            "text": "Employees get 12 weeks leave.",
            "score": 0.92,
        },
        {
            "chunk_id": str(uuid.uuid4()),
            "source_id": str(uuid.uuid4()),
            "text": "Partners receive 4 weeks paid leave.",
            "score": 0.88,
        },
    ]
    return repo


@pytest.fixture
def mock_embedding_service() -> AsyncMock:
    svc = AsyncMock()
    svc.embed_texts.return_value = [[0.1] * 1536]
    return svc


@pytest.fixture
def mock_openai_client() -> AsyncMock:
    client = AsyncMock()
    choice = MagicMock()
    choice.message.content = "The parental leave policy provides 12 weeks."
    response = MagicMock()
    response.choices = [choice]
    response.usage.prompt_tokens = 100
    response.usage.completion_tokens = 50
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


@pytest.fixture
def mock_chat_session_repo(user_id: str) -> AsyncMock:
    repo = AsyncMock()
    session_obj = MagicMock()
    session_obj.user_id = user_id
    repo.get.return_value = session_obj
    return repo


@pytest.fixture
def mock_chat_message_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.list_for_session.return_value = []
    repo.create = AsyncMock()
    return repo


@pytest.fixture
def mock_db_session() -> AsyncMock:
    return AsyncMock()
