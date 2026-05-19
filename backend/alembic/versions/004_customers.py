"""customers table + application_number sequence

Revision ID: 004
Revises: 003
Create Date: 2026-05-19 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS application_number_seq START 1")

    op.create_table(
        "customers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("application_number", sa.String(20), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("cognito_sub", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("application_number", name="uq_customers_application_number"),
        sa.UniqueConstraint("email", name="uq_customers_email"),
        sa.UniqueConstraint("cognito_sub", name="uq_customers_cognito_sub"),
    )
    op.create_index("ix_customers_application_number", "customers", ["application_number"])
    op.create_index("ix_customers_email", "customers", ["email"])
    op.create_index("ix_customers_cognito_sub", "customers", ["cognito_sub"])


def downgrade() -> None:
    op.drop_index("ix_customers_cognito_sub", table_name="customers")
    op.drop_index("ix_customers_email", table_name="customers")
    op.drop_index("ix_customers_application_number", table_name="customers")
    op.drop_table("customers")
    op.execute("DROP SEQUENCE IF EXISTS application_number_seq")
