from difflib import SequenceMatcher
from urllib.parse import urlparse


def _extract_username(url: str) -> str | None:
    """Pull first non-empty path segment as a likely username."""
    parts = [p for p in urlparse(url).path.strip("/").split("/") if p]
    return parts[0].lower() if parts else None


def _username_sim(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _content_overlap(text_a: str, text_b: str, query: str) -> float:
    """Fraction of query tokens that appear in BOTH scraped pages."""
    query_tokens = set(query.lower().split())
    if not query_tokens:
        return 0.0
    tokens_a = set(text_a.lower().split())
    tokens_b = set(text_b.lower().split())
    shared = tokens_a & tokens_b & query_tokens
    return len(shared) / len(query_tokens)


def resolve_entities(scraped_pages: list[dict], query: str) -> list[dict]:
    """
    Group pages into entity clusters using username similarity + content overlap.
    Two pages are in the same cluster if max(username_sim, content_overlap) >= 0.5.

    Returns:
        list of { entity_id, profiles: [url, ...], confidence: int }
    """
    profiles = [
        {
            "url": p["url"],
            "username": _extract_username(p["url"]),
            "content": p["content"],
        }
        for p in scraped_pages
    ]

    n = len(profiles)
    assigned = [False] * n
    groups: list[list[int]] = []

    for i in range(n):
        if assigned[i]:
            continue
        group = [i]
        assigned[i] = True
        for j in range(i + 1, n):
            if assigned[j]:
                continue
            u_sim = _username_sim(profiles[i]["username"], profiles[j]["username"])
            c_overlap = _content_overlap(
                profiles[i]["content"], profiles[j]["content"], query
            )
            if max(u_sim, c_overlap) >= 0.5:
                group.append(j)
                assigned[j] = True
        groups.append(group)

    entities: list[dict] = []
    for idx, group in enumerate(groups):
        members = [profiles[i] for i in group]
        urls = [m["url"] for m in members]
        usernames = [m["username"] for m in members if m["username"]]

        if len(group) == 1:
            confidence = 40
        else:
            sims = [
                _username_sim(usernames[a], usernames[b])
                for a in range(len(usernames))
                for b in range(a + 1, len(usernames))
            ]
            avg_sim = sum(sims) / len(sims) if sims else 0.0
            confidence = min(95, int(50 + avg_sim * 45))

        entities.append(
            {
                "entity_id": f"entity_{idx + 1}",
                "profiles": urls,
                "confidence": confidence,
            }
        )

    return entities
