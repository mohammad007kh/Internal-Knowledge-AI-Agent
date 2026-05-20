"""Unit tests for ``src.agent.prompts.render_system_prompt``.

These tests cover the FX5/RC3 three-branch behavior:

* empty chunks → canned "I don't see anything…" instruction
* non-empty chunks with high mean distance → soft "Low-confidence context" header
* non-empty chunks with low mean distance → standard grounded prompt
"""
from __future__ import annotations

from src.agent.prompts import (
    LOW_CONFIDENCE_DISTANCE_THRESHOLD,
    render_system_prompt,
)

_CANNED_PHRASE = "I don't see anything about that in the indexed sources"
_LOW_CONFIDENCE_HEADER = "Low-confidence context"


def test_empty_branch_still_renders_canned_phrase() -> None:
    """FX5/RC3: with no chunks the canned hard-refusal phrasing must
    still appear — we only soften the borderline branch.
    """
    rendered = render_system_prompt([])
    assert _CANNED_PHRASE in rendered
    assert "(No relevant context found)" in rendered
    # The "Low-confidence context" header must NOT appear in the empty branch.
    assert _LOW_CONFIDENCE_HEADER not in rendered


def test_low_confidence_branch_renders_when_mean_distance_high() -> None:
    """FX5/RC3: when chunks are present but mean distance is high the
    softened header must render and the canned hard-refusal phrasing
    must NOT appear.
    """
    chunks = [
        {"chunk_id": "c1", "text": "Project Alpha lead is unknown.", "score": 0.7},
        {"chunk_id": "c2", "text": "See annex B for the project owner.", "score": 0.7},
    ]
    # Sanity: this distance must trip the low-confidence gate.
    mean = sum(c["score"] for c in chunks) / len(chunks)
    assert mean >= LOW_CONFIDENCE_DISTANCE_THRESHOLD

    rendered = render_system_prompt(chunks)

    assert _LOW_CONFIDENCE_HEADER in rendered
    assert _CANNED_PHRASE not in rendered
    # The chunk texts are still embedded in the context block.
    assert "Project Alpha lead is unknown." in rendered
    assert "See annex B for the project owner." in rendered


def test_normal_branch_when_mean_distance_low() -> None:
    """High-confidence chunks should not trigger the low-confidence header
    or the canned refusal."""
    chunks = [
        {"chunk_id": "c1", "text": "Refunds are processed in 30 days.", "score": 0.1},
        {"chunk_id": "c2", "text": "Refund eligibility is ...", "score": 0.15},
    ]
    rendered = render_system_prompt(chunks)
    assert _LOW_CONFIDENCE_HEADER not in rendered
    assert _CANNED_PHRASE not in rendered
    assert "Refunds are processed in 30 days." in rendered


def test_chunks_without_score_default_to_normal_branch() -> None:
    """Defensive: when chunks lack a numeric ``score`` we cannot compute
    a mean distance, so we render the normal (not the low-confidence)
    branch — those chunks come from a code path that did not measure
    distance, and assuming "low confidence" would be needlessly cautious.
    """
    chunks = [{"chunk_id": "c1", "text": "Some text.", "score": None}]
    rendered = render_system_prompt(chunks)
    assert _LOW_CONFIDENCE_HEADER not in rendered
    assert _CANNED_PHRASE not in rendered
