"""Manual test harness for the Compliance Screening agent (OpenSanctions).

Run it to screen one or more people against sanctions + PEP lists in a single
OpenSanctions API call (uses the OPENSANCTIONS_API_KEY already in your .env).

Runnable from anywhere (it locates the backend dir automatically), e.g.:
    ..\\env\\Scripts\\python.exe test_compliance_agent.py        # runs TEST_CASES below
    ..\\env\\Scripts\\python.exe test_compliance_agent.py -i     # type one input at the prompt

To test your own inputs, just edit the TEST_CASES list below and re-run.
`dob` is optional and accepts an ISO date ("1952-10-07") or just a year ("1952").
This calls the LIVE OpenSanctions API — it is not mocked.
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

from app.agents.tools.opensanctions import ComplianceResult, screen_person  # noqa: E402

# ---------------------------------------------------------------------------
# EDIT ME — add / change the people you want to screen.
# ---------------------------------------------------------------------------
TEST_CASES: list[dict[str, str]] = [
    {"full_name": "Vladimir Putin", "dob": "1952-10-07"},        # expect: sanctions + PEP hit
    {"full_name": "Hisham Islah", "dob": "2003-11-01"},  # expect: clear
    {"full_name": "Shubham Singh", "dob": "200-01-01"},
]


def _print_result(full_name: str, dob: str, result: ComplianceResult) -> None:
    print("=" * 70)
    print(f"INPUT      : {full_name}" + (f"  (DOB {dob})" if dob else ""))

    if result.error:
        print(f"VERDICT    : COULD NOT SCREEN  (error: {result.error})")
        print("             -> a real run would route this to MANUAL REVIEW (fail-safe)")
        return

    sanctions = "HIT" if result.sanctions_hit else "clear"
    pep = "HIT" if result.pep_hit else "clear"
    verdict = "CLEAR" if result.clear else "MANUAL REVIEW"
    print(f"SANCTIONS  : {sanctions}")
    print(f"PEP        : {pep}")
    print(f"VERDICT    : {verdict}")
    print(f"REFERENCE  : {result.reference_id}")

    if result.matches:
        print(f"MATCHES    : {len(result.matches)}")
        for m in result.matches:
            datasets = ", ".join(m.datasets[:3]) if m.datasets else "—"
            topics = ", ".join(m.topics) if m.topics else "—"
            print(f"   - {m.caption}")
            print(f"       score {m.score:.2f} | topics: {topics}")
            print(f"       datasets: {datasets}")
            if m.url:
                print(f"       {m.url}")
    else:
        print("MATCHES    : none")


async def _run_case(full_name: str, dob: str) -> None:
    result = await screen_person(full_name=full_name, dob=dob)
    _print_result(full_name, dob, result)


async def main(interactive: bool) -> None:
    if interactive:
        full_name = input("Full name: ").strip()
        dob = input("DOB (YYYY-MM-DD or YYYY, blank to skip): ").strip()
        await _run_case(full_name, dob)
    else:
        for case in TEST_CASES:
            await _run_case(case.get("full_name", ""), case.get("dob", ""))
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Screen people against OpenSanctions (sanctions + PEP).")
    parser.add_argument(
        "-i", "--interactive", action="store_true",
        help="Type a single name + DOB at the prompt instead of running TEST_CASES.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.interactive))
