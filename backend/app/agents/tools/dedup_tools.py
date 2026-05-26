"""Async DB tools backing the Stage-3 KYC dedup layers.

Layer 1 — `find_exact_identifier_matches`: indexed equality OR across PAN /
Aadhaar / mobile / email. ~1-2ms with the indexes added in migration 007.

Layer 2 — `find_fuzzy_candidates`: pg_trgm prefilter on (dob, full_name).
Returns a small shortlist (~tens) that Python-side scoring then ranks.

Layer 3 — `find_cross_field_anomalies`: identifier reuse with a different
*other* identifier (e.g., same phone but different PAN). Catches fraud
signals that L1 misses because no single field collides.

All three exclude the current application (`application_id`) and exclude
terminal-state rows (`rejected`, `cancelled`).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application

TERMINAL_STATUSES = ("rejected", "cancelled")
FUZZY_TRGM_THRESHOLD = 0.4
FUZZY_CANDIDATE_LIMIT = 50


@dataclass(frozen=True)
class AnomalyFlag:
    kind: str          # "phone_with_different_pan" | "email_with_different_pan" | ...
    other_application_id: str
    other_field_value: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "other_application_id": self.other_application_id,
            "other_field_value": self.other_field_value,
            "detail": self.detail,
        }


def _exclude_self_and_terminal(stmt, application_id: uuid.UUID | None):
    stmt = stmt.where(Application.status.notin_(TERMINAL_STATUSES))
    if application_id is not None:
        stmt = stmt.where(Application.id != application_id)
    return stmt


async def find_exact_identifier_matches(
    db: AsyncSession,
    *,
    application_id: uuid.UUID | None,
    pan_number: str,
    aadhaar_number: str,
    email: str,
    mobile: str,
) -> list[Application]:
    """Layer 1 — exact equality on any of the four hard identifiers."""
    predicates = []
    if pan_number:
        predicates.append(Application.pan_number == pan_number)
    if aadhaar_number:
        predicates.append(Application.aadhaar_number == aadhaar_number)
    if email:
        predicates.append(Application.email == email)
    if mobile:
        predicates.append(Application.mobile == mobile)
    if not predicates:
        return []

    stmt = _exclude_self_and_terminal(
        select(Application).where(or_(*predicates)), application_id
    ).limit(5)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def find_fuzzy_candidates(
    db: AsyncSession,
    *,
    application_id: uuid.UUID | None,
    dob: date | None,
    full_name: str,
) -> list[Application]:
    """Layer 2 — DOB-equal shortlist narrowed by pg_trgm name similarity.

    pg_trgm threshold is intentionally loose (0.4) — Python-side weighted
    scoring is the real decision maker. We just want a small candidate set.
    """
    if not full_name or dob is None:
        return []

    base = select(Application).where(
        Application.dob == dob,
        text("similarity(full_name, :q_name) > :trgm_threshold"),
    )
    stmt = _exclude_self_and_terminal(base, application_id).limit(FUZZY_CANDIDATE_LIMIT)
    result = await db.execute(
        stmt, {"q_name": full_name, "trgm_threshold": FUZZY_TRGM_THRESHOLD}
    )
    return list(result.scalars().all())


async def find_cross_field_anomalies(
    db: AsyncSession,
    *,
    application_id: uuid.UUID | None,
    pan_number: str,
    aadhaar_number: str,
    email: str,
    mobile: str,
) -> list[AnomalyFlag]:
    """Layer 3 — same identifier paired with a *different* hard identifier.

    Each query returns rows that share one field with the applicant but
    differ on another (e.g., same mobile, different PAN). These aren't
    duplicates; they are fraud signals.
    """
    flags: list[AnomalyFlag] = []

    async def _scan(
        match_field, match_value: str, mismatch_field, mismatch_value: str, kind: str, detail: str
    ) -> None:
        if not match_value or not mismatch_value:
            return
        stmt = _exclude_self_and_terminal(
            select(Application).where(
                match_field == match_value,
                mismatch_field != mismatch_value,
            ),
            application_id,
        ).limit(5)
        result = await db.execute(stmt)
        for row in result.scalars().all():
            flags.append(
                AnomalyFlag(
                    kind=kind,
                    other_application_id=str(row.id),
                    other_field_value=match_value,
                    detail=detail.format(
                        match=match_value,
                        other_pan=row.pan_number,
                        other_aadhaar=row.aadhaar_number,
                    ),
                )
            )

    await _scan(
        Application.mobile, mobile, Application.pan_number, pan_number,
        "mobile_with_different_pan",
        "Mobile {match} previously used with a different PAN ({other_pan}).",
    )
    await _scan(
        Application.email, email, Application.pan_number, pan_number,
        "email_with_different_pan",
        "Email {match} previously used with a different PAN ({other_pan}).",
    )
    await _scan(
        Application.aadhaar_number, aadhaar_number, Application.pan_number, pan_number,
        "aadhaar_with_different_pan",
        "Aadhaar {match} previously paired with a different PAN ({other_pan}).",
    )
    await _scan(
        Application.pan_number, pan_number, Application.aadhaar_number, aadhaar_number,
        "pan_with_different_aadhaar",
        "PAN {match} previously paired with a different Aadhaar ({other_aadhaar}).",
    )

    return flags
