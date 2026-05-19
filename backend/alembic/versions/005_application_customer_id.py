"""applications.customer_id FK to customers

Revision ID: 005
Revises: 004
Create Date: 2026-05-19 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_applications_customer_id", "applications", ["customer_id"])


def downgrade() -> None:
    op.drop_index("ix_applications_customer_id", table_name="applications")
    op.drop_column("applications", "customer_id")
