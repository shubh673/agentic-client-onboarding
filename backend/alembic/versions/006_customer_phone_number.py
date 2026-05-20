"""customers.phone_number

Revision ID: 006
Revises: 005
Create Date: 2026-05-20 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("phone_number", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("customers", "phone_number")
