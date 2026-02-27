"""LLM client stubs — stub for T-035 tests.

Full LangChain / LangGraph integration implemented in T-060+.
``ChatOpenAI`` is re-exported here so integration tests can patch it
at ``src.agents.llm.ChatOpenAI``.
"""
from langchain_openai import ChatOpenAI  # noqa: F401 — re-exported for patching

__all__ = ["ChatOpenAI"]
