"""HTTP fetching for URLs. No parsing here."""

from __future__ import annotations

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 15.0
MAX_BODY_BYTES = 2 * 1024 * 1024  # 2 MB guard
NUM_RETRIES = 2


class FetchError(Exception):
    """Raised when fetch fails after retries or content is not usable."""

    pass


class NonHtmlError(FetchError):
    """Raised when content-type is not text/html or application/pdf."""

    pass


def _content_type_is_html_or_text(ct: str) -> bool:
    if not ct:
        return False
    ct = ct.lower().split(";")[0].strip()
    return ct in ("text/html", "text/plain", "application/xhtml+xml")


def _content_type_is_pdf(ct: str) -> bool:
    if not ct:
        return False
    ct = ct.lower().split(";")[0].strip()
    return ct == "application/pdf"


async def fetch_url(url: str) -> tuple[str, str | None, bytes | None]:
    """
    Fetch URL and return (content_type, body_text_or_none, pdf_bytes_or_none).
    For HTML: body_text is set, pdf_bytes is None.
    For PDF: body_text is None, pdf_bytes is raw bytes.
    Uses GET with redirects, retries, and a max-size guard.
    Raises NonHtmlError for unsupported content-type; FetchError on other failures.
    """
    last_error: Exception | None = None
    for attempt in range(NUM_RETRIES + 1):
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
                timeout=DEFAULT_TIMEOUT,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")

                if _content_type_is_pdf(content_type):
                    body_bytes = response.content
                    if len(body_bytes) > MAX_BODY_BYTES:
                        body_bytes = body_bytes[:MAX_BODY_BYTES]
                    return (content_type, None, body_bytes)
                if not _content_type_is_html_or_text(content_type):
                    raise NonHtmlError(f"Unsupported content-type: {content_type}")

                # Guard: don't load huge bodies into memory
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > MAX_BODY_BYTES:
                    raise FetchError(f"Response too large: {content_length} bytes")

                text = response.text
                if len(text.encode("utf-8")) > MAX_BODY_BYTES:
                    text = text[:MAX_BODY_BYTES]

                return (content_type, text, None)
        except httpx.HTTPError as e:
            last_error = e
            if attempt == NUM_RETRIES:
                raise FetchError(f"Fetch failed after {NUM_RETRIES + 1} attempts: {e}") from e
        except NonHtmlError:
            raise

    if last_error:
        raise FetchError(str(last_error)) from last_error
    raise FetchError("Fetch failed")
