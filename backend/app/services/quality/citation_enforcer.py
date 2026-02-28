import logging
from typing import TYPE_CHECKING

import httpx

from .claim_parser import split_into_claims, extract_citations

if TYPE_CHECKING:
    from app.schemas import AnswerClaim, SourceRef

logger = logging.getLogger(__name__)

REPAIR_SYSTEM_PROMPT = """You are a citation editor. Your job is to add or fix citations in the answer below.

Rules:
- Do NOT change the meaning or add new facts.
- Every sentence or bullet MUST have at least one citation like [S1], [S2], etc.
- Use ONLY source IDs that appear in the provided context.
- Spread citations across multiple sources when supported. Do not let one source dominate.
- Keep the same structure (bullets, paragraphs, etc.).
- If a claim is only supported by one source, cite that one source.
- Return ONLY the revised answer text, nothing else."""


def has_min_distinct_sources(claims: list["AnswerClaim"], min_sources: int) -> bool:
    all_ids: set[str] = set()
    for c in claims:
        all_ids.update(c.citations)
    return len(all_ids) >= min_sources


def citation_coverage(claims: list["AnswerClaim"]) -> float:
    if not claims:
        return 0.0
    cited = sum(1 for c in claims if c.citations)
    return cited / len(claims)


def _needs_repair(
    claims: list["AnswerClaim"],
    source_map: list["SourceRef"],
    min_sources: int,
    min_coverage: float,
    max_claims_single_source: int,
) -> bool:
    available_sources = len(source_map)

    cov = citation_coverage(claims)
    if cov < min_coverage:
        logger.info("Repair needed: coverage %.2f < %.2f", cov, min_coverage)
        return True

    if available_sources >= min_sources and not has_min_distinct_sources(claims, min_sources):
        logger.info("Repair needed: insufficient distinct sources")
        return True

    all_cited: set[str] = set()
    source_claim_count: dict[str, int] = {}
    for c in claims:
        for sid in c.citations:
            all_cited.add(sid)
            source_claim_count[sid] = source_claim_count.get(sid, 0) + 1

    if available_sources >= 2:
        for sid, count in source_claim_count.items():
            if count > max_claims_single_source:
                logger.info("Repair needed: source %s dominates (%d claims)", sid, count)
                return True
        cited_claims = [c for c in claims if c.citations]
        if cited_claims and len(all_cited) == 1:
            logger.info("Repair needed: all claims cite single source")
            return True

    return False


async def enforce_citations_and_multisource(
    query: str,
    draft_answer: str,
    context: str,
    source_map: list["SourceRef"],
    model: str,
    api_key: str,
    *,
    min_sources: int = 2,
    min_coverage: float = 1.0,
    max_claims_single_source: int = 2,
) -> str:
    from app.schemas import AnswerClaim

    raw_claims = split_into_claims(draft_answer)
    claims = [
        AnswerClaim(
            text=c,
            citations=extract_citations(c),
            supported=False,
            support_notes=None,
        )
        for c in raw_claims
    ]

    if not _needs_repair(claims, source_map, min_sources, min_coverage, max_claims_single_source):
        logger.info("Citation repair not needed")
        return draft_answer

    logger.info("Running citation repair call")

    source_ids = ", ".join(s.id for s in source_map)
    user_content = (
        f"Context:\n{context}\n\n"
        f"Available source IDs: {source_ids}\n\n"
        f"Original answer:\n{draft_answer}\n\n"
        f"Question: {query}\n\n"
        f"Revise the answer above so every sentence/bullet has citations and "
        f"at least {min_sources} distinct sources are used (if available). "
        f"No single source should be cited in more than {max_claims_single_source} claims unless only one source exists."
    )

    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 1500,
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()

    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        return draft_answer
    repaired = (choices[0].get("message") or {}).get("content") or ""
    repaired = repaired.strip()
    return repaired if repaired else draft_answer
