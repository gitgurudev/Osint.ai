import asyncio
import json
import logging
import time
from collections import defaultdict
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from app.core.config import get_settings
from app.models.schemas import OSINTReport, Entity, RankedSource
from app.services.search import fetch_search_urls
from app.services.scraper import scrape_page
from app.services.analyzer import run_analysis
from app.services.llm import enhance_with_llm

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ── In-memory rate limiter ────────────────────────────────────────────────────
_rate_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT   = 5    # max requests
RATE_WINDOW  = 60   # per N seconds


def _check_rate_limit(ip: str) -> bool:
    """Returns True if the request should be allowed, False if rate-limited."""
    now = time.time()
    hits = [t for t in _rate_store[ip] if now - t < RATE_WINDOW]
    _rate_store[ip] = hits
    if len(hits) >= RATE_LIMIT:
        return False
    _rate_store[ip].append(now)
    return True


app = FastAPI(
    title="OSINT AI — Digital Intelligence Engine",
    description="Search -> Scrape -> Rule-based Analysis -> GPT-4o Enhancement.",
    version="9.0.0",
)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
def serve_ui():
    return FileResponse("static/index.html")


@app.get("/api/health", tags=["health"])
def health():
    settings = get_settings()
    return {
        "status": "ok",
        "version": "9.0.0",
        "llm_enabled": settings.llm_enabled,
        "model": settings.openai_model if settings.llm_enabled else "rule-based only",
    }


def _evt(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


@app.get("/search/stream", tags=["osint"])
async def search_stream(request: Request, query: str = Query(..., min_length=2, max_length=200)):
    """SSE endpoint — emits real-time pipeline progress to the UI."""

    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {RATE_LIMIT} requests per {RATE_WINDOW}s.",
        )

    settings = get_settings()

    async def pipeline():
        # ── Stage 1: Search ───────────────────────────────────────────────────
        yield _evt({"type": "stage", "stage": "search",
                    "message": "Searching DuckDuckGo..."})

        urls = await asyncio.to_thread(fetch_search_urls, query)

        if not urls:
            yield _evt({"type": "error",
                        "message": "No search results found. Try a different query."})
            return

        yield _evt({"type": "stage_done", "stage": "search",
                    "message": f"Found {len(urls)} URLs"})

        # ── Stage 2: Scrape ───────────────────────────────────────────────────
        yield _evt({"type": "stage", "stage": "scrape",
                    "message": f"Scraping {len(urls)} pages...",
                    "total": len(urls)})

        scraped: list[dict] = []
        for i, url in enumerate(urls):
            content = await asyncio.to_thread(scrape_page, url)
            ok = bool(content and len(content) > 100)
            if ok:
                scraped.append({"url": url, "content": content})
            yield _evt({
                "type": "scrape_progress", "done": i + 1,
                "total": len(urls), "url": url, "success": ok,
            })

        if not scraped:
            yield _evt({"type": "error", "message": "All pages failed to load."})
            return

        yield _evt({"type": "stage_done", "stage": "scrape",
                    "message": f"Scraped {len(scraped)} / {len(urls)} pages"})

        # ── Stage 3: Analysis ─────────────────────────────────────────────────
        yield _evt({"type": "stage", "stage": "analyze",
                    "message": "Running rule-based analysis..."})

        rule_result = await asyncio.to_thread(run_analysis, query, scraped, None)

        yield _evt({"type": "stage_done", "stage": "analyze",
                    "message": (
                        f"{len(rule_result['profiles_found'])} profiles · "
                        f"{len(rule_result['entities'])} clusters · "
                        f"{len(rule_result['insights'])} insights"
                    )})

        # ── Stage 4: LLM ──────────────────────────────────────────────────────
        llm_result = None
        if settings.llm_enabled:
            yield _evt({"type": "stage", "stage": "llm",
                        "message": f"GPT-4o enhancement ({settings.openai_model})..."})
            llm_result = await asyncio.to_thread(
                enhance_with_llm, query, rule_result, scraped
            )
            yield _evt({"type": "stage_done", "stage": "llm",
                        "message": "Enhanced" if llm_result else "Enhancement failed"})
        else:
            yield _evt({"type": "stage_skip", "stage": "llm",
                        "message": "No API key — skipped"})

        # ── Final result ──────────────────────────────────────────────────────
        llm_enhanced = llm_result is not None
        summary  = llm_result.get("summary") if llm_enhanced else None
        insights = (llm_result.get("insights") or rule_result["insights"]) \
                   if llm_enhanced else rule_result["insights"]

        report = OSINTReport(
            query=query,
            llm_enhanced=llm_enhanced,
            summary=summary,
            email_meta=None,
            confirmed_accounts=[],
            google_footprint=None,
            hibp_result=None,
            emailrep_result=None,
            profiles_found=rule_result["profiles_found"],
            ranked_sources=[RankedSource(**s) for s in rule_result["ranked_sources"]],
            entities=[Entity(**e) for e in rule_result["entities"]],
            insights=insights,
        )

        yield _evt({"type": "result", "data": report.model_dump()})

    return StreamingResponse(
        pipeline(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/search", response_model=OSINTReport, tags=["osint"])
async def search(request: Request, query: str = Query(..., min_length=2, max_length=200)):
    """JSON endpoint for API / curl usage."""
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {RATE_LIMIT} requests per {RATE_WINDOW}s.",
        )
    settings = get_settings()

    urls = await asyncio.to_thread(fetch_search_urls, query)
    if not urls:
        raise HTTPException(404, "No search results found.")

    scraped: list[dict] = []
    for url in urls:
        content = await asyncio.to_thread(scrape_page, url)
        if content and len(content) > 100:
            scraped.append({"url": url, "content": content})
    if not scraped:
        raise HTTPException(502, "All pages failed to load.")

    rule_result = await asyncio.to_thread(run_analysis, query, scraped, None)
    llm_result  = await asyncio.to_thread(enhance_with_llm, query, rule_result, scraped) \
                  if settings.llm_enabled else None

    llm_enhanced = llm_result is not None
    return OSINTReport(
        query=query,
        llm_enhanced=llm_enhanced,
        summary=llm_result.get("summary") if llm_enhanced else None,
        email_meta=None,
        confirmed_accounts=[],
        google_footprint=None,
        hibp_result=None,
        emailrep_result=None,
        profiles_found=rule_result["profiles_found"],
        ranked_sources=[RankedSource(**s) for s in rule_result["ranked_sources"]],
        entities=[Entity(**e) for e in rule_result["entities"]],
        insights=(llm_result.get("insights") or rule_result["insights"]) if llm_enhanced else rule_result["insights"],
    )
