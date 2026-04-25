import requests
from bs4 import BeautifulSoup
from app.core.config import get_settings
from app.utils.helpers import clean_text
import logging

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}


def scrape_page(url: str) -> str | None:
    settings = get_settings()
    logger.info("[SCRAPER] Fetching: %s", url)
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=settings.scrape_timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("[SCRAPER] FAILED: %s | reason: %s", url, exc)
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "meta"]):
        tag.decompose()

    text    = soup.get_text(separator="\n")
    cleaned = clean_text(text)
    max_chars = settings.max_content_chars
    result  = cleaned[:max_chars] if len(cleaned) > max_chars else cleaned

    logger.info("[SCRAPER] OK: %s | chars=%d", url, len(result))
    return result


def scrape_urls(urls: list[str]) -> list[dict]:
    logger.info("[SCRAPER] Starting scrape | total_urls=%d", len(urls))
    results = []
    for url in urls:
        content = scrape_page(url)
        if content and len(content) > 100:
            results.append({"url": url, "content": content})
        else:
            logger.warning("[SCRAPER] Skipped (too short or empty): %s", url)

    logger.info("[SCRAPER] Done | success=%d / %d", len(results), len(urls))
    return results
