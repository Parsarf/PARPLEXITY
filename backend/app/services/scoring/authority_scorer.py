"""
Authority scoring for classified sources.
"""

from __future__ import annotations

from datetime import datetime

BASE_SCORES = {
    "peer_reviewed": 10.0,
    "preprint": 7.0,
    "gov": 8.0,
    "edu": 6.0,
    "institutional": 6.0,
    "encyclopedia": 5.0,
    "news": 3.0,
    "blog": 1.0,
    "unknown": 1.0,
}

CONFIDENCE_MULTIPLIERS = {
    "high": 1.0,
    "medium": 0.85,
    "low": 0.7,
}


def compute_authority_score(
    source_type: str,
    confidence: str,
    is_pdf: bool = False,
    pdf_metadata: dict | None = None,
    source_url: str = "",
) -> dict:
    """
    Compute a numeric authority score for a classified source.

    Args:
        source_type: Classification label from source_classifier.
        confidence: "high", "medium", or "low" from source_classifier.
        is_pdf: Whether the source is a PDF.
        pdf_metadata: Phase 8 metadata dict (for recency, citation count, etc.)
        source_url: The source URL (for any URL-based adjustments).

    Returns:
        dict with keys:
            - authority_score: float (0.0 to 15.0 range, higher = more authoritative)
            - score_breakdown: dict (component scores for debugging/transparency)
    """
    modifiers: dict = {}
    modifier_total = 0.0

    # Modifier A — Has DOI (+1.5)
    if pdf_metadata and pdf_metadata.get("doi"):
        modifiers["has_doi"] = 1.5
        modifier_total += 1.5

    # Modifier B — Recency bonus
    if pdf_metadata and isinstance(pdf_metadata.get("year"), int):
        current_year = datetime.now().year
        age = current_year - pdf_metadata["year"]
        if age <= 2:
            modifiers["recency"] = 1.0
            modifier_total += 1.0
        elif age <= 5:
            modifiers["recency"] = 0.5
            modifier_total += 0.5

    # Modifier C — Has structured sections (+1.0)
    if pdf_metadata and len(pdf_metadata.get("sections_found", [])) >= 3:
        modifiers["structured_sections"] = 1.0
        modifier_total += 1.0

    # Modifier D — PDF format bonus (+0.5)
    if is_pdf:
        modifiers["pdf_format"] = 0.5
        modifier_total += 0.5

    # Modifier E — Unstructured penalty (−2.0)
    if is_pdf:
        sections = pdf_metadata.get("sections_found", []) if pdf_metadata else []
        if len(sections) < 2 and source_type not in ("gov", "news", "encyclopedia"):
            modifiers["unstructured_penalty"] = -2.0
            modifier_total += -2.0

    base_score = BASE_SCORES.get(source_type, 1.0)
    raw_score = base_score + modifier_total
    multiplier = CONFIDENCE_MULTIPLIERS.get(confidence, 0.7)
    adjusted_score = raw_score * multiplier
    final_score = max(0.0, min(15.0, round(adjusted_score, 2)))

    return {
        "authority_score": final_score,
        "score_breakdown": {
            "base_score": base_score,
            "modifiers": modifiers,
            "modifier_total": round(modifier_total, 2),
            "confidence_multiplier": multiplier,
            "raw_score": round(raw_score, 2),
            "clamped_score": final_score,
        },
    }
