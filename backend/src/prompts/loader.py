"""Prompt loader — picks admin custom_prompt over bundled defaults.

Each pipeline node calls :func:`load_prompt` at node entry to get the
prompt text it should send to the LLM.  Resolution order:

1. ``custom`` argument (the admin-supplied ``custom_prompt`` from the
   ``llm_configurations`` row for the node's stage slot) — when non-blank.
2. Bundled file ``backend/src/prompts/{name}.v1.txt``.

Versioning is in the filename (``.v1.txt``) so future revisions can be
shipped without breaking pinned references — e.g. an admin who pasted
``v1`` into a custom prompt does not silently get ``v2`` semantics.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PROMPTS_DIR: Path = Path(__file__).resolve().parent


def load_prompt(name: str, *, custom: str | None = None) -> str:
    """Return the prompt text for *name*.

    When *custom* is non-blank, return it verbatim. Otherwise read
    ``{PROMPTS_DIR}/{name}.v1.txt``.

    Raises
    ------
    FileNotFoundError
        When *custom* is blank and no bundled template exists for *name*.
    """
    if custom is not None and custom.strip():
        return custom
    path = PROMPTS_DIR / f"{name}.v1.txt"
    if not path.is_file():
        raise FileNotFoundError(
            f"Prompt template not found for {name!r} at {path}"
        )
    return path.read_text(encoding="utf-8")
