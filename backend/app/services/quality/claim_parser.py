import re


_CITATION_PATTERN = re.compile(r"\[S(\d+)\]")
_BULLET_PATTERN = re.compile(r"^\s*(?:[-*•]|\d+[.)]\s)", re.MULTILINE)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def split_into_claims(answer: str) -> list[str]:
    if not answer or not answer.strip():
        return []

    lines = answer.strip().splitlines()
    if any(_BULLET_PATTERN.match(line) for line in lines):
        claims = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            stripped = re.sub(r"^\s*(?:[-*•]|\d+[.)]\s*)\s*", "", stripped).strip()
            if stripped:
                claims.append(stripped)
        return claims

    sentences = _SENTENCE_SPLIT.split(answer.strip())
    return [s.strip() for s in sentences if s.strip()]


def extract_citations(text: str) -> list[str]:
    if not text:
        return []
    combined = re.findall(r"\[([^\]]*S\d+[^\]]*)\]", text)
    ids: list[str] = []
    seen: set[str] = set()
    for group in combined:
        for match in re.findall(r"S\d+", group):
            if match not in seen:
                seen.add(match)
                ids.append(match)
    for match in _CITATION_PATTERN.findall(text):
        sid = f"S{match}"
        if sid not in seen:
            seen.add(sid)
            ids.append(sid)
    return ids


def remove_citation_markers(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"\s*\[S\d+(?:,\s*S\d+)*\]", "", text)
    return cleaned.strip()
