"""dedup indexes + pg_trgm extension

Revision ID: 007
Revises: 006
Create Date: 2026-05-25 00:00:00

Powers Stage-3 KYC deduplication:
- pg_trgm extension + GIN trigram index on full_name -> Layer-2 fuzzy prefilter
- B-tree indexes on dob, pan_number, aadhaar_number, mobile, email
  -> Layer-1 exact-match and Layer-3 anomaly lookups
"""
from typing import Sequence, Union

from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_applications_full_name_trgm "
        "ON applications USING gin (full_name gin_trgm_ops)"
    )
    op.create_index("ix_applications_dob", "applications", ["dob"])
    op.create_index("ix_applications_pan_number", "applications", ["pan_number"])
    op.create_index("ix_applications_aadhaar_number", "applications", ["aadhaar_number"])
    op.create_index("ix_applications_mobile", "applications", ["mobile"])
    op.create_index("ix_applications_email", "applications", ["email"])


def downgrade() -> None:
    op.drop_index("ix_applications_email", table_name="applications")
    op.drop_index("ix_applications_mobile", table_name="applications")
    op.drop_index("ix_applications_aadhaar_number", table_name="applications")
    op.drop_index("ix_applications_pan_number", table_name="applications")
    op.drop_index("ix_applications_dob", table_name="applications")
    op.execute("DROP INDEX IF EXISTS ix_applications_full_name_trgm")
