"""init applications and application_documents

Revision ID: 001
Revises:
Create Date: 2026-05-07 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    op.create_table(
        "applications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("dob", sa.Date(), nullable=False),
        sa.Column("mobile", sa.String(20), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("pan_number", sa.String(10), nullable=False),
        sa.Column("aadhaar_number", sa.String(12), nullable=False),
        sa.Column("current_stage", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(30), nullable=False, server_default="in_progress"),
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
    )

    op.create_table(
        "application_documents",
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
        sa.Column("doc_type", sa.String(20), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("stored_path", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("application_id", "doc_type", name="uq_app_doctype"),
    )
    op.create_index(
        "ix_application_documents_application_id",
        "application_documents",
        ["application_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_application_documents_application_id", table_name="application_documents")
    op.drop_table("application_documents")
    op.drop_table("applications")
