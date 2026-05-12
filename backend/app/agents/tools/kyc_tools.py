"""KYC tools — dummy stub responses for the prototype.

Swap the body of `run_kyc_check` for a real provider integration
(Refinitiv, ComplyAdvantage, in-house screening, etc.). The function
signature and return shape are what the KYCAgent + stage_runner depend on,
so keep those stable.
"""
from __future__ import annotations

import uuid


def run_kyc_check(full_name: str, pan_number: str, aadhaar_number: str) -> dict:
    """Screen the applicant against sanctions / PEP / adverse-media lists.

    Returns:
        dict with keys:
            status:        "approved" | "rejected"
            sanctions:     "clear" | "hit"
            pep:           "clear" | "hit"
            adverse_media: "no_hits" | "hits"
            reference_id:  provider reference string
    """
    return {
        "status": "approved",
        "sanctions": "clear",
        "pep": "clear",
        "adverse_media": "no_hits",
        "reference_id": f"KYC-{uuid.uuid4()}",
    }
