from typing import TYPE_CHECKING

from .citation_enforcer import citation_coverage

if TYPE_CHECKING:
    from app.schemas import AnswerClaim, AnswerQuality, SourceRef


def compute_confidence(
    claims: list["AnswerClaim"],
    source_map: list["SourceRef"],
    contradictions: bool,
) -> "AnswerQuality":
    from app.schemas import AnswerQuality

    all_ids: set[str] = set()
    for c in claims:
        all_ids.update(c.citations)
    distinct_sources_used = len(all_ids)

    coverage = citation_coverage(claims)
    unsupported_claims = sum(1 for c in claims if not c.supported)

    if (
        distinct_sources_used >= 3
        and coverage == 1.0
        and unsupported_claims == 0
        and not contradictions
    ):
        confidence = "high"
    elif (
        distinct_sources_used >= 2
        and coverage >= 0.8
        and unsupported_claims <= 1
    ):
        confidence = "medium"
    else:
        confidence = "low"

    return AnswerQuality(
        confidence=confidence,
        distinct_sources_used=distinct_sources_used,
        citation_coverage=round(coverage, 4),
        unsupported_claims=unsupported_claims,
        contradictions_detected=contradictions,
    )
