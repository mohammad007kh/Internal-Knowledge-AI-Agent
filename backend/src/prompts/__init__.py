"""Prompt templates for pipeline v2 LLM-driven nodes.

Each node loads its prompt via :func:`src.prompts.loader.load_prompt`,
which prefers the admin-supplied ``custom_prompt`` from
``llm_configurations`` and falls back to the bundled ``*.v1.txt`` file.
"""

from src.prompts.loader import load_prompt

__all__ = ["load_prompt"]
