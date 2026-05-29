"""OpenSanctions screening client — sanctions + PEP in a single API call.

One POST to the `/match/{dataset}` endpoint of the `default` collection screens
an applicant against sanctions lists, PEP lists, and other risk datasets at
once. Each matched entity carries `properties.topics`; we read those topics to
decide whether the match is a sanctions hit, a PEP hit, or other risk signal.

API contract (https://www.opensanctions.org/docs/api/):
    POST {base}/match/{dataset}
    Authorization: ApiKey <key>
    body: {"queries": {"q": {"schema": "Person",
                             "properties": {"name": [...], "birthDate": [...]}}}}
    response: {"responses": {"q": {"results": [
                  {"id", "caption", "score", "match", "datasets",
                   "properties": {"topics": [...]}}]}}}

The module never raises on a provider/network failure — it returns a
`ComplianceResult` with `error` set so the calling node can fail safe to manual
review rather than crash the pipeline.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

import httpx

from app.agents.scoring.name_scoring import screening_name_score
from app.config import get_settings

logger = logging.getLogger(__name__)

# Topic codes that classify a matched entity. See:
# https://www.opensanctions.org/docs/topics/
SANCTIONS_TOPICS = {"sanction", "sanction.linked"}
PEP_TOPICS = {"role.pep", "role.rca"}


@dataclass
class ComplianceMatch:
    """A single matched entity, kept for the compliance audit trail.

    `score` is OpenSanctions' own match score; `name_score` is our second-pass
    subset-aware name similarity; `confirmed` is whether this match survived the
    name gate (and therefore drives the sanctions/PEP hit flags).
    """

    entity_id: str
    caption: str
    score: float
    topics: list[str]
    datasets: list[str]
    url: str
    name_score: float = 0.0
    confirmed: bool = False

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "caption": self.caption,
            "score": round(self.score, 4),
            "name_score": round(self.name_score, 4),
            "confirmed": self.confirmed,
            "topics": self.topics,
            "datasets": self.datasets,
            "url": self.url,
        }


@dataclass
class ComplianceResult:
    sanctions_hit: bool = False
    pep_hit: bool = False
    matches: list[ComplianceMatch] = field(default_factory=list)
    reference_id: str = ""
    error: str | None = None

    @property
    def clear(self) -> bool:
        return not self.error and not self.sanctions_hit and not self.pep_hit


def _build_query(full_name: str, dob: str, address: str, nationality: str) -> dict:
    properties: dict[str, list[str]] = {"name": [full_name]}
    if dob:
        # OpenSanctions accepts full or partial ISO dates ("1990-01-15", "1990").
        properties["birthDate"] = [dob]
    if nationality:
        # Country/nationality mismatch penalises the score, filtering out
        # foreign near-namesakes (a common source of PEP false positives).
        properties["nationality"] = [nationality]
    if address:
        properties["address"] = [address]
    return {"queries": {"q": {"schema": "Person", "properties": properties}}}


def _entity_names(r: dict) -> list[str]:
    """All names a result is known by — caption plus name/alias properties."""
    props = r.get("properties") or {}
    names: list[str] = []
    caption = r.get("caption")
    if caption:
        names.append(str(caption))
    for key in ("name", "alias", "weakAlias"):
        names.extend(str(v) for v in (props.get(key) or []))
    # De-dup, preserve order.
    seen: set[str] = set()
    unique: list[str] = []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            unique.append(n)
    return unique


def _parse_results(
    results: list[dict],
    threshold: float,
    base_url: str,
    *,
    applicant_name: str,
    name_threshold: float,
    sanction_floor: float,
) -> ComplianceResult:
    """Turn raw /match results into a ComplianceResult, applying the name gate.

    A result only sets a sanctions/PEP hit when it is *confirmed* — its name
    matches the applicant's at/above `name_threshold`. As a safety backstop, a
    sanction-topic result with an OpenSanctions score >= `sanction_floor` is
    confirmed even if the name gate is unsure (we never silently drop a very
    confident sanctions match).
    """
    out = ComplianceResult(reference_id=f"OS-{uuid.uuid4()}")
    for r in results:
        score = float(r.get("score", 0.0) or 0.0)
        # Trust the provider's `match` flag, but never below our own threshold.
        if not (r.get("match") or score >= threshold):
            continue
        topics = list((r.get("properties") or {}).get("topics") or [])
        entity_id = str(r.get("id", ""))
        name_score = screening_name_score(applicant_name, _entity_names(r))

        is_sanction = bool(SANCTIONS_TOPICS.intersection(topics))
        is_pep = bool(PEP_TOPICS.intersection(topics))
        name_ok = name_score >= name_threshold
        sanction_forced = is_sanction and score >= sanction_floor
        confirmed = name_ok or sanction_forced

        out.matches.append(
            ComplianceMatch(
                entity_id=entity_id,
                caption=str(r.get("caption", "")),
                score=score,
                topics=topics,
                datasets=list(r.get("datasets") or []),
                url=f"{base_url.rstrip('/')}/entities/{entity_id}/" if entity_id else "",
                name_score=name_score,
                confirmed=confirmed,
            )
        )

        if is_sanction and confirmed:
            out.sanctions_hit = True
        if is_pep and name_ok:
            out.pep_hit = True
    return out


async def screen_person(
    *, full_name: str, dob: str = "", address: str = "", nationality: str = "IN"
) -> ComplianceResult:
    """Screen one person against sanctions + PEP via a single OpenSanctions call.

    `nationality` defaults to "IN" (this is an India KYC flow) to suppress
    foreign near-namesake false positives; `address` adds a weak extra signal.

    Returns a `ComplianceResult`. On a missing key, HTTP error, or unparseable
    response the result carries `error` (and no hits) so the caller can route to
    manual review instead of auto-approving.
    """
    settings = get_settings()
    api_key = settings.OPENSANCTIONS_API_KEY

    if not api_key:
        return ComplianceResult(error="no_api_key")
    if not full_name.strip():
        return ComplianceResult(error="missing_name")

    url = f"{settings.OPENSANCTIONS_BASE_URL.rstrip('/')}/match/{settings.OPENSANCTIONS_DATASET}"
    headers = {"Authorization": f"ApiKey {api_key}"}
    body = _build_query(full_name.strip(), dob.strip(), address.strip(), nationality.strip())

    try:
        async with httpx.AsyncClient(timeout=settings.OPENSANCTIONS_TIMEOUT_S) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("OpenSanctions returned %s: %s", exc.response.status_code, exc)
        return ComplianceResult(error=f"http_{exc.response.status_code}")
    except (httpx.HTTPError, ValueError) as exc:  # network error or bad JSON
        logger.warning("OpenSanctions request failed: %s", exc)
        return ComplianceResult(error="request_failed")

    query_block = (data.get("responses") or {}).get("q") or {}
    results = query_block.get("results") or []
    return _parse_results(
        results,
        settings.OPENSANCTIONS_SCORE_THRESHOLD,
        settings.OPENSANCTIONS_BASE_URL,
        applicant_name=full_name,
        name_threshold=settings.OPENSANCTIONS_NAME_THRESHOLD,
        sanction_floor=settings.OPENSANCTIONS_SANCTION_FORCE_FLOOR,
    )
