"""
OpenAI-based answer generation with citations [S1], [S2], etc.
Single retry if model omits citations.
"""

import json
import logging
import re

import httpx

SYSTEM_PROMPT = """You are a precise assistant that answers questions using ONLY the provided sources.
Rules:
- Use only the sources provided in the context below. Do not use external knowledge.
- Cite sources in square brackets like [S1], [S2] after the relevant sentence or paragraph.
- Cite every paragraph (or every sentence) that states a fact.
- If the sources do not contain enough information to answer, say so clearly (e.g. "The provided sources do not contain information about this.").
- Do not make up citations. Only use source IDs that appear in the context.
- Keep the answer concise and grounded."""

RETRY_USER_ADDON = "\n\nImportant: Add citations [S1], [S2], etc. to every paragraph. Do not answer without citations."


EVIDENCE_EXTRACTION_SYSTEM_PROMPT = """You are a research citation verifier. You will be given:
1. An answer with citation markers like [S1], [S2]
2. The source texts that were used to generate the answer
3. The original question

Your job: For each claim in the answer that has a citation, find the EXACT quote from the cited source that supports that claim.

RULES:
- Extract the EXACT text from the source. Do not paraphrase. Do not modify. Copy the exact words.
- Keep quotes between 10 and 60 words. Long enough to be meaningful, short enough to be usable.
- If a claim cites [S1], the quote MUST come from the text labeled [S1]. Do not use text from other sources.
- If you cannot find a supporting quote in the cited source, set "quote" to null.
- Do not invent or fabricate quotes. If the exact supporting text is not there, say so.

Respond with ONLY a JSON array. No other text, no markdown backticks, no explanation.

Each element in the array must be:
{
  "claim": "The claim text from the answer (without citation markers)",
  "source_id": "S1",
  "quote": "The exact text from the source that supports this claim" or null,
  "quote_context": "One sentence explaining why this quote supports the claim" or null
}

Extract evidence for every cited claim. If a claim cites multiple sources (e.g. [S1, S2]), create one entry per source."""


class OpenAIAnswerError(Exception):
    """Raised when API key is missing or OpenAI request fails."""

    pass


def has_citations(answer: str) -> bool:
    """True if answer contains at least one [S...] citation pattern with a closing bracket."""
    if not answer or not isinstance(answer, str):
        return False
    return bool(re.search(r"\[S\d+\]", answer))


async def generate_cited_answer(
    query: str,
    context: str,
    *,
    model: str,
    api_key: str,
    extra_user_instruction: str | None = None,
) -> str:
    """
    Call OpenAI Chat Completions with strict grounding rules; return generated text.
    Raises OpenAIAnswerError if API key missing or request fails.
    """
    if not api_key or not api_key.strip():
        raise OpenAIAnswerError("OPENAI_API_KEY is not set")

    user_content = f"Context:\n{context}\n\nQuestion: {query}" if context else f"Question: {query}"
    if extra_user_instruction:
        user_content = user_content + "\n\n" + extra_user_instruction
    if not user_content.strip():
        raise OpenAIAnswerError("Empty query and context")

    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": 1500,
        "temperature": 0.3,
    }
    headers = {"Authorization": f"Bearer {api_key.strip()}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise OpenAIAnswerError(f"OpenAI API error: {e.response.status_code}") from e
        except httpx.HTTPError as e:
            raise OpenAIAnswerError(f"OpenAI request failed: {e}") from e

    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise OpenAIAnswerError("OpenAI returned no choices")
    message = choices[0].get("message") or {}
    text = message.get("content") or ""
    return text.strip()


async def generate_cited_answer_with_retry(
    query: str,
    context: str,
    *,
    model: str,
    api_key: str,
) -> str:
    """
    Generate answer; if no citations found, retry once with stricter instruction.
    """
    answer = await generate_cited_answer(query, context, model=model, api_key=api_key)
    if has_citations(answer):
        return answer
    return await generate_cited_answer(
        query,
        context,
        model=model,
        api_key=api_key,
        extra_user_instruction=RETRY_USER_ADDON,
    )


async def extract_evidence_blocks(
    answer: str,
    context: str,
    source_map: list,
    query: str,
    model: str | None = None,
    api_key: str | None = None,
) -> list[dict]:
    """
    Extract structured evidence blocks (claim + exact quote + source) from the answer.
    Returns list of dicts with claim, source_id, quote, quote_context; empty list on failure.
    """
    try:
        if not answer or not answer.strip():
            return []
        if "[S" not in answer:
            return []
        if not (context or "").strip():
            return []

        from app import config as app_config

        actual_model = model or app_config.OPENAI_MODEL
        actual_key = (api_key or app_config.OPENAI_API_KEY) or ""
        if not actual_key:
            return []

        user_content = f"""Answer (with citations):
{answer}

Source texts:
{context}

Original question: {query}

Extract evidence blocks as a JSON array."""

        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": actual_model,
            "messages": [
                {"role": "system", "content": EVIDENCE_EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": 2000,
            "temperature": 0.1,
        }
        headers = {"Authorization": f"Bearer {actual_key.strip()}", "Content-Type": "application/json"}

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices") or []
        if not choices:
            return []
        response_text = (choices[0].get("message") or {}).get("content") or ""
        response_text = response_text.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[-1]
        if response_text.endswith("```"):
            response_text = response_text.rsplit("```", 1)[0]
        response_text = response_text.strip()

        try:
            evidence_blocks = json.loads(response_text)
        except json.JSONDecodeError:
            return []
        if not isinstance(evidence_blocks, list):
            return []

        cleaned = []
        for block in evidence_blocks:
            if not isinstance(block, dict):
                continue
            claim = block.get("claim", "")
            source_id = block.get("source_id", "")
            quote = block.get("quote")
            quote_context = block.get("quote_context")
            if not claim or not source_id:
                continue
            if not re.match(r"^S\d+$", source_id):
                continue
            if quote is not None and not quote.strip():
                quote = None
            cleaned.append({
                "claim": claim.strip(),
                "source_id": source_id,
                "quote": quote.strip() if quote else None,
                "quote_context": quote_context.strip() if quote_context else None,
            })
        return cleaned
    except Exception as e:
        logging.getLogger(__name__).warning("Evidence extraction failed: %s", e)
        return []
