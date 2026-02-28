import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas import AnswerClaim, ScoredChunk, SourceRef

STOPWORDS = frozenset(
    {"a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
     "have", "has", "had", "do", "does", "did", "will", "would", "could",
     "should", "may", "might", "must", "can", "to", "of", "in", "for",
     "on", "with", "at", "by", "from", "as", "it", "its", "or", "and",
     "but", "not", "no", "so", "if", "than", "that", "this", "these",
     "those", "such", "which", "what", "who", "whom", "how", "when",
     "where", "why", "all", "each", "every", "both", "few", "more",
     "most", "other", "some", "any", "only", "very", "also", "just"}
)

MIN_TOKEN_LEN = 3
MAX_KEYWORDS = 16
OVERLAP_THRESHOLD = 2


def build_source_text_lookup(
    top_chunks: list["ScoredChunk"],
    source_map: list["SourceRef"],
    chunk_id_to_sid: dict[str, str] | None = None,
) -> dict[str, str]:
    url_to_sid: dict[str, str] = {}
    for ref in source_map:
        url_to_sid[str(ref.url)] = ref.id

    sid_texts: dict[str, list[str]] = {}
    for ch in top_chunks:
        sid = None
        if chunk_id_to_sid:
            sid = chunk_id_to_sid.get(ch.chunk_id)
        if not sid:
            sid = url_to_sid.get(str(ch.source_url))
        if sid:
            sid_texts.setdefault(sid, []).append(ch.text or "")

    return {sid: "\n".join(texts) for sid, texts in sid_texts.items()}


def extract_keywords(text: str) -> set[str]:
    if not text:
        return set()
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    keywords = [t for t in tokens if len(t) >= MIN_TOKEN_LEN and t not in STOPWORDS]
    return set(keywords[:MAX_KEYWORDS])


def claim_supported_by_source(claim_text: str, source_text: str) -> tuple[bool, str]:
    if not claim_text or not source_text:
        return False, "empty claim or source text"

    claim_kw = extract_keywords(claim_text)
    source_kw = extract_keywords(source_text)
    overlap = claim_kw & source_kw
    overlap_count = len(overlap)

    source_lower = source_text.lower()
    anchor_found = False
    for kw in claim_kw:
        if len(kw) >= 4 and kw in source_lower:
            anchor_found = True
            break

    if overlap_count >= OVERLAP_THRESHOLD and anchor_found:
        return True, f"supported ({overlap_count} keyword overlaps)"

    reasons = []
    if overlap_count < OVERLAP_THRESHOLD:
        reasons.append(f"low keyword overlap ({overlap_count})")
    if not anchor_found:
        reasons.append("no anchor term found in source")
    return False, "; ".join(reasons)


def verify_claims(
    claims: list["AnswerClaim"],
    source_lookup: dict[str, str],
) -> list["AnswerClaim"]:
    from .claim_parser import remove_citation_markers

    verified: list["AnswerClaim"] = []
    for claim in claims:
        if not claim.citations:
            verified.append(claim.model_copy(update={
                "supported": False,
                "support_notes": "missing citation",
            }))
            continue

        clean_text = remove_citation_markers(claim.text)
        any_supported = False
        notes_parts: list[str] = []
        for sid in claim.citations:
            src_text = source_lookup.get(sid, "")
            if not src_text:
                notes_parts.append(f"{sid}: source text not found")
                continue
            supported, note = claim_supported_by_source(clean_text, src_text)
            if supported:
                any_supported = True
                break
            notes_parts.append(f"{sid}: {note}")

        if any_supported:
            verified.append(claim.model_copy(update={
                "supported": True,
                "support_notes": None,
            }))
        else:
            verified.append(claim.model_copy(update={
                "supported": False,
                "support_notes": "; ".join(notes_parts),
            }))

    return verified
