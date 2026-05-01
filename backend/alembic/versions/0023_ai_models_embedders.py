"""ai_models, embedders, admin_audit_log; add nullable FK columns to sources/chunks/llm_configurations.

R1 of the AI Models & Embedders rollout — additive, fully backwards-compatible.
Existing data is preserved; the new FK columns are nullable here and tightened
in revision R3.

Revision ID: 0023
Revises:     0022
Create Date: 2026-04-25
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # ai_models                                                            #
    # ------------------------------------------------------------------ #
    op.create_table(
        "ai_models",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(150), nullable=False, unique=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=True),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("api_key_encrypted", postgresql.BYTEA(), nullable=True),
        sa.Column(
            "extra_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "default_temperature",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.7"),
        ),
        sa.Column(
            "default_max_tokens",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("2048"),
        ),
        sa.Column(
            "capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_status", sa.String(16), nullable=True),
        sa.Column("last_test_error", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_ai_models_provider", "ai_models", ["provider"])
    # Composite uniqueness across provider/base_url/model_id/deployment_name.
    op.create_index(
        "ux_ai_models_provider_model",
        "ai_models",
        [
            "provider",
            "base_url",
            "model_id",
            sa.text("COALESCE(extra_config->>'deployment_name', '')"),
        ],
        unique=True,
    )

    # ------------------------------------------------------------------ #
    # embedders                                                            #
    # ------------------------------------------------------------------ #
    op.create_table(
        "embedders",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(150), nullable=False, unique=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=True),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("api_key_encrypted", postgresql.BYTEA(), nullable=True),
        sa.Column(
            "extra_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("max_input_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_status", sa.String(16), nullable=True),
        sa.Column("last_test_error", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "dimensions BETWEEN 64 AND 4096", name="embedders_dim_range"
        ),
    )
    op.create_index("ix_embedders_provider", "embedders", ["provider"])
    op.create_index(
        "ux_embedders_provider_model_dim",
        "embedders",
        ["provider", "base_url", "model_id", "dimensions"],
        unique=True,
    )
    # Partial unique — exactly one active embedder.
    op.execute(
        "CREATE UNIQUE INDEX one_active_embedder "
        "ON embedders ((is_active)) WHERE is_active = true"
    )

    # ------------------------------------------------------------------ #
    # admin_audit_log                                                      #
    # ------------------------------------------------------------------ #
    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "admin_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_admin_audit_log_admin_user_id", "admin_audit_log", ["admin_user_id"]
    )
    op.create_index(
        "ix_admin_audit_log_resource_type", "admin_audit_log", ["resource_type"]
    )
    op.create_index(
        "ix_admin_audit_log_resource_id", "admin_audit_log", ["resource_id"]
    )

    # ------------------------------------------------------------------ #
    # sources.embedder_id (NULL FK; tightened in R3)                       #
    # ------------------------------------------------------------------ #
    op.add_column(
        "sources",
        sa.Column(
            "embedder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("embedders.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index("ix_sources_embedder_id", "sources", ["embedder_id"])

    # ------------------------------------------------------------------ #
    # chunks.embedder_id (NULL FK; tightened in R3)                        #
    # ------------------------------------------------------------------ #
    op.add_column(
        "chunks",
        sa.Column(
            "embedder_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("embedders.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.create_index("ix_chunks_embedder_id", "chunks", ["embedder_id"])

    # ------------------------------------------------------------------ #
    # llm_configurations: ai_model_id FK + custom_prompt                   #
    # ------------------------------------------------------------------ #
    op.add_column(
        "llm_configurations",
        sa.Column(
            "ai_model_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai_models.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column(
        "llm_configurations",
        sa.Column("custom_prompt", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_llm_configurations_ai_model_id",
        "llm_configurations",
        ["ai_model_id"],
    )
    # Make legacy provider/model_name nullable so v2 PUT can write rows
    # without inline credentials.
    op.alter_column("llm_configurations", "provider", nullable=True)
    op.alter_column("llm_configurations", "model_name", nullable=True)


def downgrade() -> None:
    op.drop_index(
        "ix_llm_configurations_ai_model_id", table_name="llm_configurations"
    )
    op.drop_column("llm_configurations", "custom_prompt")
    op.drop_column("llm_configurations", "ai_model_id")
    op.alter_column("llm_configurations", "provider", nullable=False)
    op.alter_column("llm_configurations", "model_name", nullable=False)

    op.drop_index("ix_chunks_embedder_id", table_name="chunks")
    op.drop_column("chunks", "embedder_id")

    op.drop_index("ix_sources_embedder_id", table_name="sources")
    op.drop_column("sources", "embedder_id")

    op.drop_index("ix_admin_audit_log_resource_id", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_resource_type", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_admin_user_id", table_name="admin_audit_log")
    op.drop_table("admin_audit_log")

    op.execute("DROP INDEX IF EXISTS one_active_embedder")
    op.drop_index("ux_embedders_provider_model_dim", table_name="embedders")
    op.drop_index("ix_embedders_provider", table_name="embedders")
    op.drop_table("embedders")

    op.drop_index("ux_ai_models_provider_model", table_name="ai_models")
    op.drop_index("ix_ai_models_provider", table_name="ai_models")
    op.drop_table("ai_models")
