from urllib.parse import urlparse

_EDGE_THRESHOLD = 0.05  # minimum Jaccard similarity to create an edge
_MAX_EDGES = 20         # cap to keep response payload sane


def _jaccard(text_a: str, text_b: str) -> float:
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / len(words_a | words_b)


def _edge_weight(url_a: str, content_a: str, url_b: str, content_b: str) -> float:
    same_platform = (
        0.05
        if urlparse(url_a).netloc.lstrip("www.") == urlparse(url_b).netloc.lstrip("www.")
        else 0.0
    )
    return min(1.0, round(_jaccard(content_a, content_b) + same_platform, 3))


def build_graph(scraped_pages: list[dict]) -> dict:
    """
    Build an in-memory identity graph.

    Nodes  — one per scraped URL.
    Edges  — content similarity (Jaccard) between page pairs above threshold.
    Clusters — union-find components over edges; each cluster = likely same identity.

    Returns:
        {
            "nodes": [{"id": url, "domain": domain}, ...],
            "edges": [{"source": url, "target": url, "weight": float}, ...],
            "clusters": [[url, ...], ...]
        }
    """
    nodes = [
        {"id": p["url"], "domain": urlparse(p["url"]).netloc.lstrip("www.")}
        for p in scraped_pages
    ]

    edges: list[dict] = []
    for i, p1 in enumerate(scraped_pages):
        for j, p2 in enumerate(scraped_pages):
            if j <= i:
                continue
            w = _edge_weight(p1["url"], p1["content"], p2["url"], p2["content"])
            if w >= _EDGE_THRESHOLD:
                edges.append({"source": p1["url"], "target": p2["url"], "weight": w})

    # Union-Find for clustering
    parent = {p["url"]: p["url"] for p in scraped_pages}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path compression
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for edge in edges:
        union(edge["source"], edge["target"])

    clusters: dict[str, list[str]] = {}
    for p in scraped_pages:
        clusters.setdefault(find(p["url"]), []).append(p["url"])

    top_edges = sorted(edges, key=lambda e: e["weight"], reverse=True)[:_MAX_EDGES]

    return {
        "nodes": nodes,
        "edges": top_edges,
        "clusters": list(clusters.values()),
    }
