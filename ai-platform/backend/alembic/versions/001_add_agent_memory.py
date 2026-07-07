"""Create agent_memory table for dynamic Agent memory (v1.4).

Revision ID: 001
Revises:
Create Date: 2025-07-04 10:00:00

Stores dynamic Agent memories with two scopes:
- User-level (session_id IS NULL): shared across channels/sessions for a
  given agent + user.
- Session-level (session_id populated): strictly isolated to one session.

Indexes:
  - ix_agent_memory_user_level:   partial index on (agent_name, user_id)
                                  WHERE session_id IS NULL
  - ix_agent_memory_session_level: composite index on (agent_name, user_id,
                                  session_id)
  - ix_agent_memory_expires_at:   index on expires_at for TTL cleanup
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the agent_memory table."""
    op.create_table(
        "agent_memory",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(128), nullable=True),
        sa.Column("user_id", sa.String(128), nullable=True),
        sa.Column("memory_type", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # Single-column indexes
    op.create_index("ix_agent_memory_agent_name", "agent_memory", ["agent_name"])
    op.create_index("ix_agent_memory_session_id", "agent_memory", ["session_id"])
    op.create_index("ix_agent_memory_user_id", "agent_memory", ["user_id"])
    op.create_index("ix_agent_memory_memory_type", "agent_memory", ["memory_type"])

    # Partial index for user-level retrieval (session_id IS NULL)
    op.create_index(
        "ix_agent_memory_user_level",
        "agent_memory",
        ["agent_name", "user_id"],
        postgresql_where=sa.text("session_id IS NULL"),
    )

    # Composite index for session-level retrieval
    op.create_index(
        "ix_agent_memory_session_level",
        "agent_memory",
        ["agent_name", "user_id", "session_id"],
    )

    # Index for TTL expiry cleanup
    op.create_index(
        "ix_agent_memory_expires_at",
        "agent_memory",
        ["expires_at"],
    )


def downgrade() -> None:
    """Drop the agent_memory table."""
    op.drop_index("ix_agent_memory_expires_at", table_name="agent_memory")
    op.drop_index("ix_agent_memory_session_level", table_name="agent_memory")
    op.drop_index("ix_agent_memory_user_level", table_name="agent_memory")
    op.drop_index("ix_agent_memory_memory_type", table_name="agent_memory")
    op.drop_index("ix_agent_memory_user_id", table_name="agent_memory")
    op.drop_index("ix_agent_memory_session_id", table_name="agent_memory")
    op.drop_index("ix_agent_memory_agent_name", table_name="agent_memory")
    op.drop_table("agent_memory")
