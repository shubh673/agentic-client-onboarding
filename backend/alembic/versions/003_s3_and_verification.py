"""s3 keys and verification reason

Revision ID: 003
Revises: 002
Create Date: 2026-05-08 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "application_documents",
        "stored_path",
        new_column_name="s3_key",
        existing_type=sa.String(500),
        existing_nullable=False,
    )
    op.add_column(
        "applications",
        sa.Column("verification_reason", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("applications", "verification_reason")
    op.alter_column(
        "application_documents",
        "s3_key",
        new_column_name="stored_path",
        existing_type=sa.String(500),
        existing_nullable=False,
    )
