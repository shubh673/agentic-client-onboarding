"""Manual test harness for the full KYC agent (dedup L1/L2/L3 + compliance).

Runs an applicant through the complete KYC LangGraph and prints the live log
trail (the "KYC agent invoked / Dedup L1 / L2 / L3 / compliance" lines) plus the
final decision.

Runnable from anywhere (it locates the backend dir automatically), e.g.:
    ..\\env\\Scripts\\python.exe test_kyc_agent.py            # runs TEST_CASES below
    ..\\env\\Scripts\\python.exe test_kyc_agent.py -i         # type one applicant at the prompt

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
import os
import sys
from pathlib import Path


def _find_backend_dir(start: Path) -> Path:
    """Walk upward to the backend dir (the one holding app/config.py)."""
    for d in (start, *start.parents):
        if (d / "app" / "config.py").exists():
            return d
    return start


# Make this runnable from anywhere (backend/, backend/test/, …): put the backend
# dir on sys.path so `app` imports, and chdir there so pydantic-settings finds .env.
_BACKEND_DIR = _find_backend_dir(Path(__file__).resolve().parent)
sys.path.insert(0, str(_BACKEND_DIR))
os.chdir(_BACKEND_DIR)

# Windows consoles default to cp1252; force UTF-8 so em-dashes, accented names
# and ₹ in agent messages / entity captions print correctly.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from app.agents.kyc import KYCAgent, KYCResult  # noqa: E402

# ---------------------------------------------------------------------------
# EDIT ME — add / change the applicants you want to run through KYC.
# Fields: full_name, pan_number, aadhaar_number, email, mobile, dob (ISO),
#         address, application_id (optional — leave out / None for a new applicant).
# (full_name + dob + address are forwarded to OpenSanctions, with nationality=IN.)
#
# These four cases are built against the existing DB record (status=completed):
#   Hisham Islah | DOB 2003-11-01 | PAN ABCDE1234G | Aadhaar 123456789124
#                | mobile +918078808923 | hisham.islah@arttechgroup.com
# so dedup has something to collide with. Expect, in order: L1 reject,
# L2 manual review, L3 manual review, then a fully-clear approval.
# ---------------------------------------------------------------------------
TEST_CASES: list[dict[str, str]] = [
    # CASE 1 — L1 CATCH (exact identifier duplicate).
    # Reuses Hisham's real PAN / Aadhaar / email / mobile -> Layer 1 fires.
    # Expect: REJECTED (duplicate_identifier); L2/L3/compliance never run.
    {
        "full_name": "Hisham Islah",
        "pan_number": "ABCDE1234G",
        "aadhaar_number": "123456789124",
        "email": "hisham.islah@arttechgroup.com",
        "mobile": "+918078808923",
        "dob": "2003-11-01",
        "address": "kakkanad",
    },
    # CASE 2 — L1 PASSES, L2 FLAGS (fuzzy name + same DOB).
    # All four identifiers are NEW (so Layer 1, which only compares identifiers,
    # finds nothing) but the name matches "Hisham Islah" and the DOB is the same
    # 2003-11-01 -> Layer 2 scores it a duplicate.
    # Expect: MANUAL REVIEW (possible_duplicate_fuzzy); L3/compliance never run.
    # Tip: tweak the spelling (e.g. "Hisham Islaah") to exercise fuzzy tolerance.
    {
        "full_name": "Hisham Isla",
        "pan_number": "PQRSX6789L",
        "aadhaar_number": "987654321098",
        "email": "hisham.alt@example.com",
        "mobile": "+919999900000",
        "dob": "2003-11-01",
        "address": "kakkanad",
    },
    # CASE 3 — L1 & L2 PASS, L3 FLAGS (cross-field anomaly / fraud signal).
    # Reuses Hisham's MOBILE (+918078808923) but with a DIFFERENT PAN, Aadhaar,
    # name and DOB. L1 (PAN/Aadhaar only) finds nothing; L2 finds nothing
    # (different name + DOB); L3 spots the mobile reused with a different PAN.
    # Expect: MANUAL REVIEW (cross_field_anomaly).
    {
        "full_name": "Shubham Singh",
        "pan_number": "ABCDE9999Z",
        "aadhaar_number": "555566667777",
        "email": "shubham.singh@example.com",
        "mobile": "+918078808923",
        "dob": "1995-05-05",
        "address": "Mumbai",
    },
    # CASE 4 — ALL THREE CLEAR (fresh applicant) -> compliance -> approval.
    # Different name, different DOB, all-new identifiers: L1/L2/L3 clear, the
    # OpenSanctions check is clean. Expect: APPROVED.
    {
        "full_name": "Shubham Singh",
        "pan_number": "LMNOP4567Q",
        "aadhaar_number": "111122223333",
        "email": "shubham.singh@example.com",
        "mobile": "+919812345678",
        "dob": "1992-06-20",
        "address": "Bengaluru",
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
            address=case.get("address", ""),
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
            "address": input("Address: ").strip(),
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
