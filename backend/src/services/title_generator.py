"""TitleGeneratorService — generate short chat-session titles via the titler stage.

Used by ``POST /chat/sessions/{id}/messages`` on the very first user turn
to replace the placeholder ``"New chat"`` title with a 3–7 word summary
of the user's question.  Runs synchronously before the SSE stream starts
with a hard 2-second timeout — any failure (timeout, LLM error, empty
output) falls back silently to the placeholder so chat is never blocked.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from src.prompts.loader import load_prompt

if TYPE_CHECKING:
    from src.services.ai_model_resolver import AIModelResolver

logger = logging.getLogger(__name__)

_STAGE = "titler"
_MAX_TITLE_LEN = 60
# Characters stripped from the leading and trailing edges of the LLM's
# raw output.  Whitespace handles incidental padding; the quote/period set
# handles the common failure modes from chat-style models that wrap their
# answer in quotes or append a sentence-final period.
_STRIP_CHARS = " \t\n\r\"'`.!?"


class TitleGeneratorService:
    """Resolve the ``titler`` stage and produce a short title from one message."""

    def __init__(self, ai_model_resolver: AIModelResolver) -> None:
        self._resolver = ai_model_resolver

    async def generate_title(
        self,
        user_message: str,
        *,
        timeout_s: float = 2.0,
    ) -> str | None:
        """Return a short title for *user_message* or ``None`` on any failure.

        On success returns a stripped, capped (≤60 chars) string.  On
        timeout, LLM error, refusal, or empty output returns ``None`` —
        the caller is expected to leave the existing title untouched.
        """
        if not user_message or not user_message.strip():
            return None

        try:
            return await asyncio.wait_for(
                self._call_llm(user_message),
                timeout=timeout_s,
            )
        except TimeoutError:
            logger.warning("title_generator: timed out after %.1fs", timeout_s)
            return None
        except Exception:  # noqa: BLE001 — never propagate to the chat path
            logger.warning("title_generator: LLM call failed", exc_info=True)
            return None

    async def _call_llm(self, user_message: str) -> str | None:
        client = await self._resolver.resolve(_STAGE)
        system_prompt = load_prompt(_STAGE, custom=client.custom_prompt)
        response = await client.http_client.chat.completions.create(
            model=client.model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=client.temperature,
            max_tokens=client.max_tokens,
        )
        raw = (response.choices[0].message.content or "").strip()
        return _normalise_title(raw)


def _normalise_title(raw: str) -> str | None:
    """Strip quotes/whitespace/trailing punctuation, cap at 60 chars.

    Returns ``None`` when the result would be empty after cleanup.
    """
    if not raw:
        return None
    cleaned = raw.strip(_STRIP_CHARS)
    # A second strip pass: models sometimes prefix "Title:" — drop it.
    lower = cleaned.lower()
    if lower.startswith("title:"):
        cleaned = cleaned[len("title:") :].strip(_STRIP_CHARS)
    if not cleaned:
        return None
    if len(cleaned) > _MAX_TITLE_LEN:
        cleaned = cleaned[:_MAX_TITLE_LEN].rstrip(_STRIP_CHARS)
    return cleaned or None
