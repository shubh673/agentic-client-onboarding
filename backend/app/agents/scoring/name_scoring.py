"""Weighted multi-algorithm name similarity for KYC dedup Layer 2.

Combines four signals so the score holds up across the failure modes a single
algorithm struggles with:

- token_sort_ratio   -> word reordering ("Rohit Kumar Singh" vs "Singh Rohit Kumar")
- WRatio             -> typos and partial matches
- jaro_winkler       -> prefix-weighted, good for short/initialed names
- metaphone equality -> vernacular spelling drift ("Krishnan" / "Krishna" / "Krsna")

The weighted score lands in [0.0, 1.0]. The full per-signal breakdown is
returned so a compliance reviewer can see *why* a record was flagged.
"""
from __future__ import annotations

import re
from typing import TypedDict

import jellyfish
from rapidfuzz import fuzz

WEIGHT_TOKEN_SORT = 0.45
WEIGHT_WRATIO = 0.25
WEIGHT_JARO_WINKLER = 0.20
WEIGHT_METAPHONE = 0.10

FUZZY_DUPLICATE_THRESHOLD = 0.85


class NameScore(TypedDict):
    rapidfuzz_token_sort: float
    rapidfuzz_wratio: float
    jaro_winkler: float
    metaphone_match: float
    weighted_score: float


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _metaphone_score(a: str, b: str) -> float:
    """Per-token metaphone with Jaro-Winkler fallback.

    Whole-string metaphone is order-sensitive ("Rohit Kumar Singh" hashes
    differently from "Singh Rohit Kumar") and brittle for tiny spelling
    drift ("Krishnan" -> 'KRXNN', "Krishna" -> 'KRXN').

    Per-token + best-match handles both: each token from the shorter name
    finds its best phonetic match in the longer name; we average those.
    """
    tok_a = [jellyfish.metaphone(t) for t in a.split() if t]
    tok_b = [jellyfish.metaphone(t) for t in b.split() if t]
    tok_a = [t for t in tok_a if t]
    tok_b = [t for t in tok_b if t]
    if not tok_a or not tok_b:
        return 0.0

    short, long = (tok_a, tok_b) if len(tok_a) <= len(tok_b) else (tok_b, tok_a)
    per_token = [
        max(jellyfish.jaro_winkler_similarity(s, l) for l in long) for s in short
    ]
    return sum(per_token) / len(per_token)


def score_name_match(name_a: str, name_b: str) -> NameScore:
    """Return per-signal scores + weighted total, each in [0.0, 1.0]."""
    a = _normalize(name_a)
    b = _normalize(name_b)

    if not a or not b:
        return NameScore(
            rapidfuzz_token_sort=0.0,
            rapidfuzz_wratio=0.0,
            jaro_winkler=0.0,
            metaphone_match=0.0,
            weighted_score=0.0,
        )

    token_sort = fuzz.token_sort_ratio(a, b) / 100.0
    wratio = fuzz.WRatio(a, b) / 100.0
    jw = jellyfish.jaro_winkler_similarity(a, b)
    meta = _metaphone_score(a, b)

    weighted = (
        WEIGHT_TOKEN_SORT * token_sort
        + WEIGHT_WRATIO * wratio
        + WEIGHT_JARO_WINKLER * jw
        + WEIGHT_METAPHONE * meta
    )

    return NameScore(
        rapidfuzz_token_sort=round(token_sort, 4),
        rapidfuzz_wratio=round(wratio, 4),
        jaro_winkler=round(jw, 4),
        metaphone_match=meta,
        weighted_score=round(weighted, 4),
    )


def is_fuzzy_duplicate(score: NameScore, threshold: float = FUZZY_DUPLICATE_THRESHOLD) -> bool:
    return score["weighted_score"] >= threshold
