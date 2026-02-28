import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas import AnswerClaim

_NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?%?")
_POLARITY_POSITIVE = {"always", "all", "every", "true", "yes", "correct", "is", "are", "can", "will"}
_POLARITY_NEGATIVE = {"never", "none", "no", "false", "not", "incorrect", "cannot", "won't", "isn't", "aren't"}


def _extract_numbers(text: str) -> list[str]:
    return _NUMBER_PATTERN.findall(text)


def _extract_polarity(text: str) -> str | None:
    words = set(text.lower().split())
    has_pos = bool(words & _POLARITY_POSITIVE)
    has_neg = bool(words & _POLARITY_NEGATIVE)
    if has_pos and not has_neg:
        return "positive"
    if has_neg and not has_pos:
        return "negative"
    return None


def detect_contradictions(
    claims: list["AnswerClaim"],
    source_lookup: dict[str, str],
) -> bool:
    if len(claims) < 2:
        return False

    distinct_sources: set[str] = set()
    for c in claims:
        distinct_sources.update(c.citations)
    if len(distinct_sources) < 2:
        return False

    from .claim_parser import remove_citation_markers

    claim_data: list[tuple[str, list[str], list[str], str | None]] = []
    for c in claims:
        clean = remove_citation_markers(c.text)
        numbers = _extract_numbers(clean)
        polarity = _extract_polarity(clean)
        claim_data.append((clean, c.citations, numbers, polarity))

    for i in range(len(claim_data)):
        for j in range(i + 1, len(claim_data)):
            ci_text, ci_cites, ci_nums, ci_pol = claim_data[i]
            cj_text, cj_cites, cj_nums, cj_pol = claim_data[j]

            ci_sources = set(ci_cites)
            cj_sources = set(cj_cites)
            if ci_sources == cj_sources:
                continue

            ci_words = set(ci_text.lower().split())
            cj_words = set(cj_text.lower().split())
            common_words = ci_words & cj_words - {"the", "a", "an", "is", "are", "of", "to", "in", "and", "or"}
            if len(common_words) < 2:
                continue

            if ci_nums and cj_nums and ci_nums != cj_nums:
                return True

            if ci_pol and cj_pol and ci_pol != cj_pol:
                return True

    return False


def add_disagreement_note(answer: str, claims: list["AnswerClaim"]) -> str:
    from .claim_parser import remove_citation_markers

    source_claims: dict[str, list[str]] = {}
    for c in claims:
        clean = remove_citation_markers(c.text)
        for sid in c.citations:
            source_claims.setdefault(sid, []).append(clean)

    sources_involved = list(source_claims.keys())
    if len(sources_involved) < 2:
        return answer

    refs = ", ".join(f"[{s}]" for s in sources_involved[:3])
    note = f"\n\n**Note:** Sources {refs} may present differing information on this topic. Cross-check specific claims with the original sources."
    return answer + note
