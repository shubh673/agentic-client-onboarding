"""Stage 3 — KYC LangGraph subgraph.

Three layers run in sequence, short-circuiting on hit:

    START
      |-> dedup_l1_exact      (PAN/Aadhaar/mobile/email collision)
      |     hit  -> terminate_reject          -> END
      |     clear ->
      |-> dedup_l2_fuzzy      (name + DOB, weighted multi-algorithm score)
      |     hit  -> terminate_manual_review   -> END
      |     clear ->
      |-> dedup_l3_anomaly    (cross-field reuse with a different PAN, etc.)
      |     hit  -> terminate_manual_review   -> END
      |     clear ->
      |-> compliance_screening (OpenSanctions sanctions + PEP; hit -> manual review)
      |-> adverse_media_scan  (today: passthrough; later: LLM + web search)
      |-> aggregate           -> END

Reusability
-----------
The compiled graph is exposed via `build_kyc_graph()` / `get_kyc_graph()` so
any other LangGraph can plug it in as a subgraph:

    from app.agents.kyc import build_kyc_graph
    parent.add_node("kyc", build_kyc_graph())

Runtime dependencies — DB session, log sink, stage number — flow through
`RunnableConfig["configurable"]`, not through state. That keeps the parent's
state schema free of KYC internals: it only has to carry the input fields
(`full_name`, `pan_number`, `aadhaar_number`, `email`, `mobile`, `dob`,
`application_id`) and read back the result fields (`approved`,
`manual_review`, `final_reason`).

Stage-3 backwards compatibility
-------------------------------
`KYCAgent.run(...)` is preserved as a thin adapter so the existing
`stage_runner._play_stage_3` keeps working — it just gets richer kwargs
(application_id, email, mobile, dob) and a richer `KYCResult` back.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.kyc_nodes import (
    adverse_media_scan,
    aggregate,
    compliance_screening,
    dedup_l1_exact,
    dedup_l2_fuzzy,
    dedup_l3_anomaly,
    dedup_route,
    terminate_manual_review,
    terminate_reject,
)
from app.database import SessionLocal

EmitLog = Callable[[int, str, str], Awaitable[None]]


class KYCState(TypedDict, total=False):
    # Inputs
    application_id: Optional[str]
    full_name: str
    dob: str
    mobile: str
    email: str
    pan_number: str
    aadhaar_number: str

    # Dedup outputs
    dedup_decision: str        # "clear" | "duplicate" | "suspicious"
    dedup_layer: int           # 0 (cleared) | 1 | 2 | 3
    dedup_matches: list[dict[str, Any]]
    dedup_anomalies: list[dict[str, Any]]
    dedup_score_breakdown: dict[str, Any]

    # Compliance screening outputs (OpenSanctions sanctions + PEP)
    sanctions_status: str
    pep_status: str
    compliance_matches: list[dict[str, Any]]
    adverse_media_findings: str
    risk_decision: str
    reference_id: str

    # Final outcome
    approved: bool
    manual_review: bool
    final_reason: str


@dataclass
class KYCResult:
    approved: bool = False
    manual_review: bool = False
    final_reason: str = ""
    reference_id: str = ""
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

_graph = None


def build_kyc_graph():
    """Build and compile the KYC subgraph.

    No checkpointer — the KYC subgraph is short-lived and stateless across
    invocations. A parent graph can wrap this with its own checkpointer if
    it needs durable resume semantics.
    """
    g = StateGraph(KYCState)

    g.add_node("dedup_l1_exact", dedup_l1_exact)
    g.add_node("dedup_l2_fuzzy", dedup_l2_fuzzy)
    g.add_node("dedup_l3_anomaly", dedup_l3_anomaly)
    g.add_node("terminate_reject", terminate_reject)
    g.add_node("terminate_manual_review", terminate_manual_review)
    g.add_node("compliance_screening", compliance_screening)
    g.add_node("adverse_media_scan", adverse_media_scan)
    g.add_node("aggregate", aggregate)

    g.add_edge(START, "dedup_l1_exact")

    g.add_conditional_edges(
        "dedup_l1_exact",
        dedup_route,
        {
            "terminate_reject": "terminate_reject",
            "terminate_manual_review": "terminate_manual_review",
            "continue": "dedup_l2_fuzzy",
        },
    )
    g.add_conditional_edges(
        "dedup_l2_fuzzy",
        dedup_route,
        {
            "terminate_reject": "terminate_reject",
            "terminate_manual_review": "terminate_manual_review",
            "continue": "dedup_l3_anomaly",
        },
    )
    g.add_conditional_edges(
        "dedup_l3_anomaly",
        dedup_route,
        {
            "terminate_reject": "terminate_reject",
            "terminate_manual_review": "terminate_manual_review",
            "continue": "compliance_screening",
        },
    )

    g.add_edge("compliance_screening", "adverse_media_scan")
    g.add_edge("adverse_media_scan", "aggregate")
    g.add_edge("aggregate", END)
    g.add_edge("terminate_reject", END)
    g.add_edge("terminate_manual_review", END)

    return g.compile()


def get_kyc_graph():
    global _graph
    if _graph is None:
        _graph = build_kyc_graph()
    return _graph


# ---------------------------------------------------------------------------
# Adapter — preserves the legacy KYCAgent.run(...) call shape used by
# stage_runner so the orchestrator only needs a small kwargs update.
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _maybe_session(db: AsyncSession | None):
    """Yield the passed session if non-None, otherwise open a fresh one."""
    if db is not None:
        yield db
        return
    async with SessionLocal() as session:
        yield session


class KYCAgent:
    """Thin wrapper around the compiled KYC graph.

    The plug-and-play unit is `build_kyc_graph()` / `get_kyc_graph()`. This
    class exists so existing callers (stage_runner, future callers wanting a
    one-shot result object) don't have to deal with raw LangGraph state.
    """

    STAGE = 3

    async def run(
        self,
        *,
        full_name: str,
        pan_number: str,
        aadhaar_number: str,
        emit_log: EmitLog,
        application_id: uuid.UUID | str | None = None,
        email: str = "",
        mobile: str = "",
        dob: str = "",
        db: AsyncSession | None = None,
    ) -> KYCResult:
        await emit_log(self.STAGE, "info", "KYC agent invoked")

        graph = get_kyc_graph()
        initial_state: KYCState = {
            "application_id": str(application_id) if application_id else None,
            "full_name": full_name,
            "pan_number": pan_number,
            "aadhaar_number": aadhaar_number,
            "email": email,
            "mobile": mobile,
            "dob": dob,
        }

        async with _maybe_session(db) as session:
            config = {
                "configurable": {
                    "db_session": session,
                    "emit_log": emit_log,
                    "stage": self.STAGE,
                }
            }
            try:
                final = await graph.ainvoke(initial_state, config=config)
            except Exception as exc:  # noqa: BLE001
                await emit_log(self.STAGE, "error", f"KYC agent error: {exc}")
                return KYCResult(
                    approved=False,
                    manual_review=False,
                    final_reason="kyc_agent_error",
                    reference_id="",
                    details={"error": str(exc)},
                )

        return KYCResult(
            approved=bool(final.get("approved", False)),
            manual_review=bool(final.get("manual_review", False)),
            final_reason=str(final.get("final_reason", "")),
            reference_id=str(final.get("reference_id", "")),
            details=dict(final),
        )
