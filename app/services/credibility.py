from urllib.parse import urlparse

# Base credibility scores per known domain
_DOMAIN_SCORES: dict[str, float] = {
    "github.com": 0.9,
    "linkedin.com": 0.85,
    "kaggle.com": 0.80,
    "huggingface.co": 0.80,
    "stackoverflow.com": 0.70,
    "twitter.com": 0.75,
    "x.com": 0.75,
    "youtube.com": 0.65,
    "dev.to": 0.60,
    "facebook.com": 0.60,
    "instagram.com": 0.60,
    "reddit.com": 0.55,
    "medium.com": 0.50,
    "substack.com": 0.50,
}

_BLOG_KEYWORDS = {"blog", "about", "portfolio", "personal", "home"}
_DEFAULT_SCORE = 0.20
_BLOG_SCORE = 0.40


def score_url(url: str) -> float:
    netloc = urlparse(url).netloc.lower().removeprefix("www.")
    for domain, score in _DOMAIN_SCORES.items():
        if netloc == domain or netloc.endswith("." + domain):
            return score
    if any(kw in netloc for kw in _BLOG_KEYWORDS):
        return _BLOG_SCORE
    return _DEFAULT_SCORE


def rank_sources(scraped_pages: list[dict]) -> list[dict]:
    """
    Annotate each page with a credibility_score and return sorted high→low.
    The original content dict is extended, not replaced.
    """
    scored = [
        {**page, "credibility_score": score_url(page["url"])}
        for page in scraped_pages
    ]
    return sorted(scored, key=lambda p: p["credibility_score"], reverse=True)
