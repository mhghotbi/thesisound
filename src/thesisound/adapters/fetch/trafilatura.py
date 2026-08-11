from __future__ import annotations

from dataclasses import dataclass

from thesisound.config import Settings


class UrlFetchError(RuntimeError):
    """Raised when Trafilatura cannot download or extract usable page text."""


@dataclass(frozen=True, slots=True)
class UrlFetchResult:
    title: str
    markdown: str
    canonical_url: str
    text_characters: int
    extractor: str = "trafilatura"


def fetch_and_extract_url(url: str, *, settings: Settings) -> UrlFetchResult:
    """Fetch a single URL and extract main content as Markdown via Trafilatura."""

    try:
        import trafilatura
        from trafilatura.settings import use_config
    except ImportError as error:
        raise UrlFetchError(
            "Trafilatura is not installed. Install thesisound with the "
            "url-fetch or web-ui extra."
        ) from error

    config = use_config()
    config.set("DEFAULT", "DOWNLOAD_TIMEOUT", str(settings.url_fetch_timeout_seconds))

    downloaded = trafilatura.fetch_url(url, config=config)
    if not downloaded:
        raise UrlFetchError("page download failed")

    document = trafilatura.bare_extraction(
        downloaded,
        url=url,
        include_comments=False,
        include_tables=True,
        favor_recall=True,
        with_metadata=True,
    )
    if document is None:
        raise UrlFetchError("no extractable main text")

    markdown = trafilatura.extract(
        downloaded,
        url=url,
        output_format="markdown",
        include_comments=False,
        include_tables=True,
        favor_recall=True,
        with_metadata=False,
    )
    if not markdown or not markdown.strip():
        raise UrlFetchError("extracted text was empty")

    title = (getattr(document, "title", None) or "").strip() or _fallback_title(url)
    canonical = (getattr(document, "url", None) or "").strip() or url
    cleaned = markdown.strip() + "\n"
    if not cleaned.lstrip().startswith("#"):
        cleaned = f"# {title}\n\n{cleaned}"

    return UrlFetchResult(
        title=title,
        markdown=cleaned,
        canonical_url=canonical,
        text_characters=len(cleaned),
    )


def _fallback_title(url: str) -> str:
    from urllib.parse import urlparse

    path = urlparse(url).path.rstrip("/")
    leaf = path.rsplit("/", 1)[-1] if path else ""
    return leaf.replace("-", " ").replace("_", " ").strip() or url
