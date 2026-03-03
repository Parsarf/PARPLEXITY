"""
Evidence pipeline: extract quotes, verify them, assign page numbers.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def build_evidence_blocks(
    answer: str,
    context: str,
    source_map: list,
    query: str,
    top_chunks: list,
    chunk_id_to_sid: dict[str, str],
    source_text_lookup: dict[str, str],
) -> list[dict]:
    """
    Full evidence pipeline: extract evidence blocks via OpenAI, verify quotes, assign page numbers.
    Returns list of evidence block dicts with quote_verified, quote_match_score, quote_match_type, page_number.
    """
    try:
        from app.services.answer.openai_answerer import extract_evidence_blocks
        from app.services.quality.quote_verifier import verify_quotes, assign_page_numbers

        raw_blocks = await extract_evidence_blocks(
            answer=answer,
            context=context,
            source_map=source_map,
            query=query,
        )

        if not raw_blocks:
            logger.info("No evidence blocks extracted from answer")
            return []

        verified_blocks = verify_quotes(
            evidence_blocks=raw_blocks,
            source_text_lookup=source_text_lookup,
        )

        assign_page_numbers(
            evidence_blocks=verified_blocks,
            chunks=top_chunks,
            chunk_id_to_sid=chunk_id_to_sid,
        )

        total = len(verified_blocks)
        verified_count = sum(1 for b in verified_blocks if b.get("quote_verified"))
        logger.info("Evidence: %s/%s quotes verified", verified_count, total)

        return verified_blocks

    except Exception as e:
        logger.warning("Evidence pipeline failed: %s", e)
        return []
