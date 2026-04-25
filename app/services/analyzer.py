"""
Rule-based OSINT intelligence engine.
Zero external API calls — all logic is deterministic Python.
"""

import re
from difflib import SequenceMatcher
from urllib.parse import urlparse

# ── 1. Source credibility ─────────────────────────────────────────────────────

_DOMAIN_SCORES: dict[str, float] = {
    "github.com": 0.90,
    "linkedin.com": 0.85,
    "kaggle.com": 0.80,
    "huggingface.co": 0.80,
    "stackoverflow.com": 0.75,
    "twitter.com": 0.75,
    "x.com": 0.75,
    "youtube.com": 0.65,
    "dev.to": 0.65,
    "reddit.com": 0.55,
    "facebook.com": 0.55,
    "instagram.com": 0.55,
    "medium.com": 0.50,
    "substack.com": 0.50,
    "hashnode.com": 0.55,
    "producthunt.com": 0.60,
    "npmjs.com": 0.70,
    "pypi.org": 0.70,
}

_BLOG_KEYWORDS = {"blog", "about", "portfolio", "personal", "home"}
_DEFAULT_SCORE = 0.20
_BLOG_SCORE = 0.40


def _score_url(url: str) -> float:
    netloc = urlparse(url).netloc.lower().removeprefix("www.")
    for domain, score in _DOMAIN_SCORES.items():
        if netloc == domain or netloc.endswith("." + domain):
            return score
    if any(kw in netloc for kw in _BLOG_KEYWORDS):
        return _BLOG_SCORE
    return _DEFAULT_SCORE


# ── 2. Platform identification ────────────────────────────────────────────────

_PLATFORMS: dict[str, list[str]] = {
    "GitHub": ["github.com"],
    "LinkedIn": ["linkedin.com"],
    "Twitter/X": ["twitter.com", "x.com"],
    "Stack Overflow": ["stackoverflow.com"],
    "Kaggle": ["kaggle.com"],
    "HuggingFace": ["huggingface.co"],
    "YouTube": ["youtube.com"],
    "Reddit": ["reddit.com"],
    "Dev.to": ["dev.to"],
    "Medium": ["medium.com"],
    "npm": ["npmjs.com"],
    "PyPI": ["pypi.org"],
    "Product Hunt": ["producthunt.com"],
    "Hashnode": ["hashnode.com"],
}


def _detect_platform(url: str) -> str:
    netloc = urlparse(url).netloc.lower().removeprefix("www.")
    for platform, domains in _PLATFORMS.items():
        for domain in domains:
            if netloc == domain or netloc.endswith("." + domain):
                return platform
    return "Web"


def _is_profile_url(url: str, score: float) -> bool:
    """Heuristic: a URL on a known platform with a short path is likely a profile."""
    if score < 0.50:
        return False
    path_parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
    # GitHub profile: github.com/username (1 segment)
    # LinkedIn: linkedin.com/in/username (2 segments, first = "in")
    # Twitter: twitter.com/username (1 segment)
    return len(path_parts) <= 2


# ── 3. Username extraction ────────────────────────────────────────────────────

def _extract_username(url: str) -> str | None:
    parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
    # skip LinkedIn's "in" and "pub" prefixes
    skip = {"in", "pub", "user", "u", "profile"}
    for part in parts:
        if part.lower() not in skip:
            return part.lower()
    return None


def _username_sim(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


# ── 4. Content signal extractors ──────────────────────────────────────────────

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

_SKILL_KEYWORDS = {
    "python", "javascript", "typescript", "java", "golang", "go", "rust",
    "c++", "c#", "kotlin", "swift", "php", "ruby", "scala",
    "react", "vue", "angular", "nextjs", "svelte",
    "node", "django", "fastapi", "flask", "express",
    "machine learning", "deep learning", "nlp", "computer vision",
    "data science", "artificial intelligence", "llm", "generative ai",
    "docker", "kubernetes", "terraform", "ansible",
    "aws", "gcp", "azure", "cloud",
    "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
    "linux", "git", "graphql", "rest api", "microservices", "devops",
}

# Cities and countries — extend as needed
_LOCATION_RE = re.compile(
    r"\b(Mumbai|Delhi|Bangalore|Bengaluru|Hyderabad|Chennai|Pune|Kolkata|Ahmedabad|"
    r"New York|San Francisco|Los Angeles|Seattle|Boston|Austin|Chicago|"
    r"London|Berlin|Amsterdam|Paris|Toronto|Vancouver|Sydney|Singapore|Dubai|"
    r"India|USA|United States|UK|United Kingdom|Germany|Canada|Australia)\b",
    re.IGNORECASE,
)


def _extract_emails(text: str) -> list[str]:
    return sorted(set(_EMAIL_RE.findall(text)))


def _extract_skills(text: str) -> list[str]:
    lower = text.lower()
    return sorted(skill for skill in _SKILL_KEYWORDS if skill in lower)


def _extract_locations(text: str) -> list[str]:
    return sorted(set(m.group().title() for m in _LOCATION_RE.finditer(text)))


def _query_in_content(content: str, query: str) -> bool:
    """Check if any query token appears in the page content."""
    tokens = query.lower().split()
    lower_content = content.lower()
    return any(t in lower_content for t in tokens if len(t) > 2)


# ── 5. Entity grouping ────────────────────────────────────────────────────────

def _group_into_entities(profiles: list[dict], query: str) -> list[dict]:
    """
    Greedy single-pass clustering.
    Two pages merge into one entity when:
      username similarity >= 0.6  OR  query-token content overlap >= 0.5
    """
    n = len(profiles)
    assigned = [False] * n
    groups: list[list[int]] = []
    query_tokens = set(t for t in query.lower().split() if len(t) > 2)

    for i in range(n):
        if assigned[i]:
            continue
        group = [i]
        assigned[i] = True
        for j in range(i + 1, n):
            if assigned[j]:
                continue
            u_sim = _username_sim(profiles[i]["username"], profiles[j]["username"])

            tokens_i = set(profiles[i]["content"].lower().split())
            tokens_j = set(profiles[j]["content"].lower().split())
            overlap = (
                len(tokens_i & tokens_j & query_tokens) / len(query_tokens)
                if query_tokens
                else 0.0
            )

            if max(u_sim, overlap) >= 0.5:
                group.append(j)
                assigned[j] = True
        groups.append(group)

    entities: list[dict] = []
    for idx, group in enumerate(groups):
        members = [profiles[i] for i in group]
        sources = [m["url"] for m in members]

        avg_cred = sum(m["score"] for m in members) / len(members)
        # More corroborating sources → higher confidence, capped at 95
        corroboration_bonus = min(0.25, 0.08 * (len(group) - 1))
        confidence = min(95, int((avg_cred + corroboration_bonus) * 100))

        entities.append({"id": f"entity_{idx + 1}", "confidence": confidence, "sources": sources})

    return entities


# ── 6. Insight generation ─────────────────────────────────────────────────────

def _email_insights(meta: dict) -> list[str]:
    """Generate insights specific to an email input."""
    insights = []
    atype = meta["account_type"]

    if atype == "personal":
        insights.append(
            f"Email provider: {meta['provider']} (personal account) — "
            f"username hint: '{meta['username']}'"
        )
    elif atype == "corporate":
        insights.append(
            f"Corporate email detected — domain: {meta['domain']} — "
            f"likely affiliated with this organisation"
        )
    elif atype == "educational":
        insights.append(
            f"Educational email detected — domain: {meta['domain']} — "
            f"possibly a student or faculty member"
        )

    if meta["name_guess"] != meta["username"]:
        insights.append(f"Probable real name derived from email: {meta['name_guess']}")

    return insights


def _generate_insights(
    query: str,
    scraped_pages: list[dict],
    profiles_found: list[str],
    ranked_sources: list[dict],
    email_meta: dict | None = None,
) -> list[str]:
    insights: list[str] = []
    all_content = " ".join(p["content"] for p in scraped_pages)

    # Email-specific insights at the top (if applicable)
    if email_meta:
        insights.extend(_email_insights(email_meta))

    # Platform presence (de-duplicated)
    seen_platforms: set[str] = set()
    for page in scraped_pages:
        plat = _detect_platform(page["url"])
        if plat != "Web" and plat not in seen_platforms:
            seen_platforms.add(plat)
            insights.append(f"Active on {plat}: {page['url']}")

    # Emails
    emails = _extract_emails(all_content)
    for email in emails[:3]:
        insights.append(f"Email address found: {email}")

    # Skills / technologies
    skills = _extract_skills(all_content)
    if skills:
        top_skills = ", ".join(skills[:12])
        insights.append(f"Detected technologies / skills: {top_skills}")

    # Locations
    locations = _extract_locations(all_content)
    if locations:
        insights.append(f"Location signals: {', '.join(locations[:5])}")

    # Digital footprint summary
    n = len(profiles_found)
    if n >= 4:
        insights.append(f"Strong public digital presence: {n} profile pages found across platforms.")
    elif n >= 1:
        insights.append(f"Moderate digital presence: {n} profile page(s) identified.")
    else:
        insights.append("No definitive profile pages found; indirect mentions only.")

    # High-credibility sources
    high_cred = [r for r in ranked_sources if r["credibility_score"] >= 0.75]
    if high_cred:
        urls = ", ".join(r["url"] for r in high_cred[:3])
        insights.append(f"High-credibility sources (score >= 0.75): {urls}")

    # Warn if most data is from low-credibility sources
    low_cred_ratio = sum(1 for r in ranked_sources if r["credibility_score"] < 0.4) / max(
        len(ranked_sources), 1
    )
    if low_cred_ratio > 0.6:
        insights.append(
            "Majority of results are from low-credibility sources - treat findings with caution."
        )

    return insights


# ── 7. Public entry point ─────────────────────────────────────────────────────

def run_analysis(query: str, scraped_pages: list[dict], email_meta: dict | None = None) -> dict:
    """
    Full rule-based OSINT analysis pipeline.
    Input:  query string + list of {url, content} dicts from scraper.
    Output: dict matching OSINTReport schema.
    """
    if not scraped_pages:
        return {
            "query": query,
            "profiles_found": [],
            "ranked_sources": [],
            "entities": [],
            "insights": ["No data could be scraped for this query."],
        }

    # Rank sources by credibility
    ranked_sources = sorted(
        [{"url": p["url"], "credibility_score": _score_url(p["url"])} for p in scraped_pages],
        key=lambda x: x["credibility_score"],
        reverse=True,
    )

    # Identify likely profile pages
    profiles_found = [
        p["url"]
        for p in scraped_pages
        if _is_profile_url(p["url"], _score_url(p["url"])) and _query_in_content(p["content"], query)
    ]

    # Build per-page metadata for entity grouping
    page_meta = [
        {
            "url": p["url"],
            "username": _extract_username(p["url"]),
            "content": p["content"],
            "score": _score_url(p["url"]),
        }
        for p in scraped_pages
    ]

    entities = _group_into_entities(page_meta, query)
    insights = _generate_insights(query, scraped_pages, profiles_found, ranked_sources, email_meta)

    return {
        "query": query,
        "profiles_found": profiles_found,
        "ranked_sources": ranked_sources,
        "entities": entities,
        "insights": insights,
    }
