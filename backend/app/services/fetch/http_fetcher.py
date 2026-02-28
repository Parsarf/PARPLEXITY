"""HTTP fetching for URLs. No parsing here."""

from typing import Tuple

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
    """Raised when content-type is PDF or not text/html."""

    pass


def _is_pdf_url(url: str) -> bool:
    url_lower = url.lower().strip()
    return url_lower.endswith(".pdf") or ".pdf?" in url_lower


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


async def fetch_url(url: str) -> Tuple[str, str]:
    """
    Fetch URL and return (content_type, body_text).
    Uses GET with redirects, retries, and a max-size guard.
    Raises NonHtmlError for PDF or non-text/html; FetchError on other failures.
    """
    if _is_pdf_url(url):
        raise NonHtmlError("PDF URLs are skipped")

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
                    raise NonHtmlError("Content-Type is PDF")
                if not _content_type_is_html_or_text(content_type):
                    raise NonHtmlError(f"Unsupported content-type: {content_type}")

                # Guard: don't load huge bodies into memory
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > MAX_BODY_BYTES:
                    raise FetchError(f"Response too large: {content_length} bytes")

                text = response.text
                if len(text.encode("utf-8")) > MAX_BODY_BYTES:
                    text = text[:MAX_BODY_BYTES]

                return content_type, text
        except httpx.HTTPError as e:
            last_error = e
            if attempt == NUM_RETRIES:
                raise FetchError(f"Fetch failed after {NUM_RETRIES + 1} attempts: {e}") from e
        except NonHtmlError:
            raise

    if last_error:
        raise FetchError(str(last_error)) from last_error
    raise FetchError("Fetch failed")
