"""Manual test harness for the full KYC agent (dedup L1/L2/L3 + compliance).

Runs an applicant through the complete KYC LangGraph and prints the live log
trail (the "KYC agent invoked / Dedup L1 / L2 / L3 / compliance" lines) plus the
final decision.

    cd backend
    env\\Scripts\\python.exe test_kyc_agent.py            # runs TEST_CASES below
    env\\Scripts\\python.exe test_kyc_agent.py -i         # type one applicant at the prompt

To test your own inputs, edit the TEST_CASES list below and re-run.

Requirements / notes:
  * Postgres must be running on :5433 — the dedup layers query the DB
    (start it with `docker compose up` from the repo root if it is not).
  * The compliance step makes a LIVE OpenSanctions call (key from .env).
  * Dedup EXCLUDES the application itself by `application_id`. To trigger an
    L1 duplicate against a row already in the DB, leave `application_id` as None
    (or set a different id) and reuse that row's PAN / Aadhaar / email / mobile.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from app.agents.kyc import KYCAgent, KYCResult

# Windows consoles default to cp1252; force UTF-8 so em-dashes, accented names
# and ₹ in agent messages / entity captions print correctly.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

# ---------------------------------------------------------------------------
# EDIT ME — add / change the applicants you want to run through KYC.
# Fields: full_name, pan_number, aadhaar_number, email, mobile, dob (ISO),
#         application_id (optional — leave out / None for a brand-new applicant).
# ---------------------------------------------------------------------------
TEST_CASES: list[dict[str, str]] = [
    {
        "full_name": "Aarav Sharma",
        "pan_number": "ABCDE1234F",
        "aadhaar_number": "123412341234",
        "email": "aarav.sharma@example.com",
        "mobile": "9876543210",
        "dob": "1990-01-15",
    },
    {
        "full_name": "Vladimir Putin",
        "pan_number": "ZZZZZ9999Z",
        "aadhaar_number": "999999999999",
        "email": "vp@example.com",
        "mobile": "9000000000",
        "dob": "1952-10-07",
    },
]

# Pretty markers for each log level the agent emits.
_LEVEL_MARKERS = {
    "info": "[INFO] ",
    "success": "[ OK ] ",
    "warning": "[WARN] ",
    "error": "[FAIL] ",
}


async def emit_log(stage: int, level: str, message: str) -> None:
    """Print a streamed agent log line (the EmitLog callback contract)."""
    marker = _LEVEL_MARKERS.get(level, f"[{level.upper()}] ")
    print(f"  {marker} {message}")


def _print_summary(result: KYCResult) -> None:
    if result.approved:
        outcome = "APPROVED"
    elif result.manual_review:
        outcome = "MANUAL REVIEW"
    else:
        outcome = "REJECTED"

    d = result.details or {}
    print("  " + "-" * 66)
    print(f"  OUTCOME    : {outcome}")
    print(f"  REASON     : {result.final_reason or '—'}")
    print(f"  REFERENCE  : {result.reference_id or '—'}")
    print(f"  DEDUP      : decision={d.get('dedup_decision', '—')} layer={d.get('dedup_layer', '—')}")
    if d.get("dedup_matches"):
        print(f"  DEDUP HITS : {d['dedup_matches']}")
    if d.get("dedup_anomalies"):
        print(f"  ANOMALIES  : {d['dedup_anomalies']}")
    print(f"  SCREENING  : sanctions={d.get('sanctions_status', '—')} pep={d.get('pep_status', '—')}")
    if d.get("compliance_matches"):
        for m in d["compliance_matches"]:
            print(f"     - {m.get('caption')} | score {m.get('score')} | topics {m.get('topics')}")


async def _run_case(case: dict[str, str]) -> None:
    print("=" * 70)
    print(f"APPLICANT  : {case.get('full_name', '')}  "
          f"(PAN {case.get('pan_number', '')}, DOB {case.get('dob', '')})")
    print("  " + "-" * 66)
    try:
        result = await KYCAgent().run(
            full_name=case.get("full_name", ""),
            pan_number=case.get("pan_number", ""),
            aadhaar_number=case.get("aadhaar_number", ""),
            email=case.get("email", ""),
            mobile=case.get("mobile", ""),
            dob=case.get("dob", ""),
            application_id=case.get("application_id"),
            emit_log=emit_log,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL]  Could not run KYC: {exc}")
        print("          Is Postgres up on :5433? Try `docker compose up` from the repo root.")
        return
    _print_summary(result)


async def main(interactive: bool) -> None:
    if interactive:
        case = {
            "full_name": input("Full name: ").strip(),
            "pan_number": input("PAN: ").strip(),
            "aadhaar_number": input("Aadhaar: ").strip(),
            "email": input("Email: ").strip(),
            "mobile": input("Mobile: ").strip(),
            "dob": input("DOB (YYYY-MM-DD): ").strip(),
        }
        await _run_case(case)
    else:
        for case in TEST_CASES:
            await _run_case(case)
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run applicants through the full KYC agent (dedup + compliance).")
    parser.add_argument(
        "-i", "--interactive", action="store_true",
        help="Type a single applicant at the prompt instead of running TEST_CASES.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.interactive))
