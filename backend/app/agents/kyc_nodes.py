"""LangGraph node functions for the KYC subgraph.

Each node is `async (state, config) -> dict-of-state-updates`. Runtime
dependencies — `db_session`, `emit_log`, `stage` — are pulled from
`config["configurable"]`. This is what makes the graph plug-and-play: a
parent LangGraph injects its own DB session and log sink at invocation
time, and these nodes pick them up without the parent's State schema
needing to know anything about KYC internals.

Decision flow (kept in sync with `build_kyc_graph` in `kyc.py`):
  L1 hit       -> terminate_reject          (status=rejected,       reason=duplicate_identifier)
  L2 hit       -> terminate_manual_review   (status=manual_review,  reason=possible_duplicate_fuzzy)
  L3 hit       -> terminate_manual_review   (status=manual_review,  reason=cross_field_anomaly)
  all clear    -> compliance_screening -> adverse_media_scan -> aggregate (status driven by screening)
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agents.scoring.name_scoring import (
    FUZZY_DUPLICATE_THRESHOLD,
    is_fuzzy_duplicate,
    score_name_match,
)
from app.agents.tools.dedup_tools import (
    find_cross_field_anomalies,
    find_exact_identifier_matches,
    find_fuzzy_candidates,
)
from app.agents.tools.kyc_tools import run_kyc_check
from app.agents.tools.opensanctions import screen_person
from app.config import get_settings

logger = logging.getLogger(__name__)


def _cfg(config: RunnableConfig, key: str, default: Any = None) -> Any:
    return (config.get("configurable") or {}).get(key, default)


async def _emit(config: RunnableConfig, level: str, message: str) -> None:
    """Forward a log line through the caller-supplied sink, if any."""
    emit_log = _cfg(config, "emit_log")
    stage = _cfg(config, "stage", 3)
    if emit_log is None:
        return
    await emit_log(stage, level, message)


def _coerce_dob(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    return None


def _coerce_app_id(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


async def dedup_l1_exact(state: dict, config: RunnableConfig) -> dict:
    db = _cfg(config, "db_session")
    await _emit(config, "info", "Dedup L1: exact-match identifier scan (PAN / Aadhaar)")

    if db is None:
        await _emit(config, "warning", "Dedup L1 skipped: no DB session available")
        return {"dedup_decision": "clear", "dedup_layer": 0, "dedup_matches": []}

    matches = await find_exact_identifier_matches(
        db,
        application_id=_coerce_app_id(state.get("application_id")),
        pan_number=state.get("pan_number", ""),
        aadhaar_number=state.get("aadhaar_number", ""),
    )

    if not matches:
        await _emit(config, "success", "Dedup L1: no identifier collisions")
        return {"dedup_decision": "clear", "dedup_layer": 0, "dedup_matches": []}

    serialized = [
        {
            "application_id": str(m.id),
            "matched_pan": m.pan_number == state.get("pan_number"),
            "matched_aadhaar": m.aadhaar_number == state.get("aadhaar_number"),
            "matched_email": m.email == state.get("email"),
            "matched_mobile": m.mobile == state.get("mobile"),
            "status": m.status,
        }
        for m in matches
    ]
    await _emit(
        config,
        "error",
        f"Dedup L1: exact identifier match against application {serialized[0]['application_id']}",
    )
    return {
        "dedup_decision": "duplicate",
        "dedup_layer": 1,
        "dedup_matches": serialized,
    }


async def dedup_l2_fuzzy(state: dict, config: RunnableConfig) -> dict:
    db = _cfg(config, "db_session")
    await _emit(config, "info", "Dedup L2: fuzzy name + DOB match")

    if db is None:
        await _emit(config, "warning", "Dedup L2 skipped: no DB session available")
        return {"dedup_decision": "clear", "dedup_layer": 0, "dedup_matches": []}

    dob = _coerce_dob(state.get("dob"))
    full_name = state.get("full_name", "")

    if not full_name or dob is None:
        await _emit(config, "info", "Dedup L2: insufficient input (name/DOB missing), skipping")
        return {"dedup_decision": "clear", "dedup_layer": 0}

    candidates = await find_fuzzy_candidates(
        db,
        application_id=_coerce_app_id(state.get("application_id")),
        dob=dob,
        full_name=full_name,
    )

    if not candidates:
        await _emit(config, "success", "Dedup L2: no DOB-matched candidates")
        return {"dedup_decision": "clear", "dedup_layer": 0, "dedup_score_breakdown": {}}

    scored: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    for cand in candidates:
        score = score_name_match(full_name, cand.full_name)
        record = {
            "application_id": str(cand.id),
            "candidate_name": cand.full_name,
            "score": score,
        }
        scored.append(record)
        if best is None or score["weighted_score"] > best["score"]["weighted_score"]:
            best = record

    breakdown = {
        "threshold": FUZZY_DUPLICATE_THRESHOLD,
        "candidate_count": len(scored),
        "best_match": best,
        "all_candidates": scored,
    }

    if best is not None and is_fuzzy_duplicate(best["score"]):
        await _emit(
            config,
            "error",
            (
                f"Dedup L2: likely fuzzy duplicate (score "
                f"{best['score']['weighted_score']:.2f}) against application "
                f"{best['application_id']}"
            ),
        )
        return {
            "dedup_decision": "duplicate",
            "dedup_layer": 2,
            "dedup_matches": [best],
            "dedup_score_breakdown": breakdown,
        }

    best_score = best["score"]["weighted_score"] if best else 0.0
    await _emit(
        config,
        "success",
        f"Dedup L2: {len(scored)} candidate(s) scored, no fuzzy duplicate (best {best_score:.2f})",
    )
    return {
        "dedup_decision": "clear",
        "dedup_layer": 0,
        "dedup_score_breakdown": breakdown,
    }


async def dedup_l3_anomaly(state: dict, config: RunnableConfig) -> dict:
    db = _cfg(config, "db_session")
    await _emit(config, "info", "Dedup L3: cross-field anomaly scan")

    if db is None:
        await _emit(config, "warning", "Dedup L3 skipped: no DB session available")
        return {"dedup_decision": "clear", "dedup_layer": 0, "dedup_anomalies": []}

    flags = await find_cross_field_anomalies(
        db,
        application_id=_coerce_app_id(state.get("application_id")),
        pan_number=state.get("pan_number", ""),
        aadhaar_number=state.get("aadhaar_number", ""),
        email=state.get("email", ""),
        mobile=state.get("mobile", ""),
    )

    if not flags:
        await _emit(config, "success", "Dedup L3: no cross-field anomalies")
        return {"dedup_decision": "clear", "dedup_layer": 0, "dedup_anomalies": []}

    serialized = [f.to_dict() for f in flags]
    await _emit(
        config,
        "error",
        f"Dedup L3: {len(flags)} cross-field anomaly flag(s) — {flags[0].detail}",
    )
    return {
        "dedup_decision": "suspicious",
        "dedup_layer": 3,
        "dedup_anomalies": serialized,
    }


def dedup_route(state: dict) -> str:
    """Conditional edge — fan out of each dedup node."""
    decision = state.get("dedup_decision")
    if decision == "duplicate" and state.get("dedup_layer") == 1:
        return "terminate_reject"
    if decision in ("duplicate", "suspicious"):
        return "terminate_manual_review"
    return "continue"


# ---------------------------------------------------------------------------
# Compliance screening — sanctions + PEP in a single OpenSanctions call.
# Falls back to the dummy run_kyc_check stub only when no API key is set so
# local dev / demos still flow through to later stages.
# ---------------------------------------------------------------------------

async def _stub_screening(config: RunnableConfig, state: dict) -> dict:
    """Dev fallback when OPENSANCTIONS_API_KEY is unset — keeps the demo flowing."""
    await _emit(config, "warning", "Compliance screening: stub mode (no API key configured)")
    response = await asyncio.to_thread(
        run_kyc_check,
        state.get("full_name", ""),
        state.get("pan_number", ""),
        state.get("aadhaar_number", ""),
    )
    sanctions = response.get("sanctions", "clear")
    pep = response.get("pep", "clear")
    await _emit(config, "success" if sanctions == "clear" else "error", f"Sanctions screening: {sanctions}")
    await _emit(config, "success" if pep == "clear" else "error", f"PEP screening: {pep}")
    return {
        "sanctions_status": sanctions,
        "pep_status": pep,
        "reference_id": response.get("reference_id", ""),
        "compliance_matches": [],
        "risk_decision": "clear" if response.get("status") == "approved" else "manual_review",
    }


async def compliance_screening(state: dict, config: RunnableConfig) -> dict:
    """Screen the applicant against sanctions + PEP via one OpenSanctions call."""
    await _emit(config, "info", "Compliance screening: sanctions + PEP (OpenSanctions)")

    if not get_settings().OPENSANCTIONS_API_KEY:
        return await _stub_screening(config, state)

    result = await screen_person(
        full_name=state.get("full_name", ""),
        dob=state.get("dob", ""),
        address=state.get("address", ""),
    )

    if result.error:
        # Fail safe: never auto-approve when screening could not run.
        await _emit(config, "error", f"Compliance screening unavailable ({result.error}) — routing to manual review")
        return {
            "sanctions_status": "error",
            "pep_status": "error",
            "reference_id": result.reference_id,
            "compliance_matches": [],
            "risk_decision": "manual_review",
        }

    # Surface each matched entity for the audit trail, separating confirmed
    # matches (drive the decision) from namesakes dropped by the name gate.
    for m in result.matches:
        datasets = ", ".join(m.datasets[:3]) if m.datasets else "—"
        topics = ", ".join(m.topics) or "—"
        if m.confirmed:
            await _emit(
                config,
                "error",
                f"Screening match: {m.caption} ({datasets}; topics {topics}; "
                f"score {m.score:.2f}; name {m.name_score:.2f})",
            )
        else:
            await _emit(
                config,
                "info",
                f"Possible namesake dismissed (name {m.name_score:.2f} < threshold): "
                f"{m.caption} (topics {topics}; score {m.score:.2f})",
            )

    sanctions = "hit" if result.sanctions_hit else "clear"
    pep = "hit" if result.pep_hit else "clear"
    await _emit(config, "success" if sanctions == "clear" else "error", f"Sanctions screening: {sanctions}")
    await _emit(config, "success" if pep == "clear" else "error", f"PEP screening: {pep}")

    return {
        "sanctions_status": sanctions,
        "pep_status": pep,
        "reference_id": result.reference_id,
        "compliance_matches": [m.to_dict() for m in result.matches],
        "risk_decision": "clear" if result.clear else "manual_review",
    }


async def adverse_media_scan(state: dict, config: RunnableConfig) -> dict:
    """Scaffold for the LLM-driven adverse-media web search.

    Today: replays the value already produced by `risk_screening` so the
    log trail is unchanged. Future: structured LLM call with web search
    enabled over (name + DOB year + city/state).
    """
    finding = state.get("adverse_media_findings", "not_screened")
    await _emit(config, "info", "Adverse media scan")
    # TODO(adverse-media): replace with structured LLM + web search call.
    await _emit(
        config,
        "error" if finding == "hits" else "info",
        f"Adverse media: {finding}",
    )
    return {"adverse_media_findings": finding}


# ---------------------------------------------------------------------------
# Terminal nodes
# ---------------------------------------------------------------------------

async def terminate_reject(state: dict, config: RunnableConfig) -> dict:
    matches = state.get("dedup_matches") or []
    other = matches[0].get("application_id") if matches else "unknown"
    await _emit(
        config,
        "error",
        f"KYC rejected: duplicate identifier (matches application {other})",
    )
    return {
        "approved": False,
        "manual_review": False,
        "final_reason": "duplicate_identifier",
    }


async def terminate_manual_review(state: dict, config: RunnableConfig) -> dict:
    layer = state.get("dedup_layer")
    if layer == 2:
        reason = "possible_duplicate_fuzzy"
    elif layer == 3:
        reason = "cross_field_anomaly"
    else:
        reason = "manual_review_required"

    await _emit(
        config,
        "warning",
        f"KYC flagged for manual review: {reason}",
    )
    return {
        "approved": False,
        "manual_review": True,
        "final_reason": reason,
    }


async def aggregate(state: dict, config: RunnableConfig) -> dict:
    """Happy path — dedup cleared, screening done. Compose the final outcome."""
    risk = state.get("risk_decision", "clear")
    reference_id = state.get("reference_id", "")

    if risk == "clear":
        await _emit(
            config,
            "success",
            f"KYC approved (reference {reference_id})",
        )
        await _emit(
            config,
            "success",
            "Stage 3 complete — handing off to Eligibility agent",
        )
        return {
            "approved": True,
            "manual_review": False,
            "final_reason": "clear",
        }

    if state.get("sanctions_status") == "hit":
        reason = "sanctions_hit"
    elif state.get("pep_status") == "hit":
        reason = "pep_hit"
    else:
        reason = "compliance_manual_review"

    await _emit(
        config,
        "warning",
        f"KYC flagged for manual review by compliance screening: {reason} (reference {reference_id})",
    )
    return {
        "approved": False,
        "manual_review": True,
        "final_reason": reason,
    }
