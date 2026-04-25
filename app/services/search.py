import logging
from ddgs import DDGS
from app.core.config import get_settings
from app.utils.helpers import deduplicate_urls, is_email, parse_email

logger = logging.getLogger(__name__)


def _ddg_search(query: str, max_results: int) -> list[str]:
    """Single DuckDuckGo search — returns list of URLs."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return [r["href"] for r in results if r.get("href")]
    except Exception as exc:
        logger.error("[SEARCH] DuckDuckGo failed | query=%r | error=%s", query, exc)
        return []


def fetch_search_urls(query: str) -> list[str]:
    """
    Smart search dispatcher:
    - Plain name/username  → 1 search
    - Email address        → 3 searches (email + name + username on social platforms)
    Returns deduplicated list of URLs.
    """
    settings = get_settings()
    n = settings.search_num_results

    if is_email(query):
        return _fetch_urls_for_email(query, n)

    # Standard name/username search
    logger.info("[SEARCH] Mode=name | query=%r | max=%d", query, n)
    urls = _ddg_search(query, n)
    urls = deduplicate_urls(urls)
    logger.info("[SEARCH] Done | found=%d unique URLs", len(urls))
    return urls


def _fetch_urls_for_email(email: str, max_results: int) -> list[str]:
    """
    Run 3 targeted searches for an email address and merge results.

    Search 1 — direct email mention:    "john.doe@gmail.com"
    Search 2 — name-based search:       "John Doe"
    Search 3 — username on platforms:   "johndoe" site:github.com OR site:linkedin.com
    """
    meta = parse_email(email)
    logger.info(
        "[SEARCH] Mode=email | email=%s | name_guess=%r | username=%r | type=%s",
        email, meta["name_guess"], meta["username"], meta["account_type"],
    )

    per_search = max(5, max_results // 2)

    # Search 1 — exact email
    logger.info("[SEARCH] Search 1/3 — exact email: %r", email)
    urls_1 = _ddg_search(f'"{email}"', per_search)
    logger.info("[SEARCH] Search 1 results: %d", len(urls_1))

    # Search 2 — guessed name
    logger.info("[SEARCH] Search 2/3 — name: %r", meta["name_guess"])
    urls_2 = _ddg_search(meta["name_guess"], per_search)
    logger.info("[SEARCH] Search 2 results: %d", len(urls_2))

    # Search 3 — username on social platforms
    username_query = (
        f'{meta["username"]} site:github.com OR site:linkedin.com '
        f'OR site:twitter.com OR site:x.com OR site:dev.to'
    )
    logger.info("[SEARCH] Search 3/3 — username on platforms: %r", meta["username"])
    urls_3 = _ddg_search(username_query, per_search)
    logger.info("[SEARCH] Search 3 results: %d", len(urls_3))

    # Merge in priority order: social platforms first, then name, then direct email
    all_urls = urls_3 + urls_2 + urls_1
    urls = deduplicate_urls(all_urls)

    logger.info("[SEARCH] Done | total_unique=%d URLs from 3 searches", len(urls))
    return urls
