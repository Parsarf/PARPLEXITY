"""
OpenAI-based answer generation with citations [S1], [S2], etc.
Single retry if model omits citations.
"""

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
