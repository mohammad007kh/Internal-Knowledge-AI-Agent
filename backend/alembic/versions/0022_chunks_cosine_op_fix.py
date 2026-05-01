"""Documentation-only revision: chunk_repository.similarity_search now uses
the cosine operator ``<=>`` so the existing ``vector_cosine_ops`` HNSW
index is actually used.  No DDL changes here — the index already exists
from revision 0007.

Revision ID: 0022
Revises:     0021
Create Date: 2026-04-25
"""

from __future__ import annotations

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No DDL — see chunk_repository.similarity_search for the operator fix."""
    pass


def downgrade() -> None:
    pass
