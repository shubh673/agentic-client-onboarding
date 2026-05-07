"""application_logs table for per-application event traceability

Revision ID: 002
Revises: 001
Create Date: 2026-05-07 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "application_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "application_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", sa.SmallInteger(), nullable=False),
        sa.Column("level", sa.String(16), nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_application_logs_application_id",
        "application_logs",
        ["application_id"],
    )
    op.create_index("ix_application_logs_ts", "application_logs", ["ts"])


def downgrade() -> None:
    op.drop_index("ix_application_logs_ts", table_name="application_logs")
    op.drop_index("ix_application_logs_application_id", table_name="application_logs")
    op.drop_table("application_logs")
