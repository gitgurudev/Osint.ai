import asyncio
import json
import logging
from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from app.core.config import get_settings
from app.models.schemas import OSINTReport, Entity, RankedSource, EmailMeta
from app.services.search import fetch_search_urls
from app.services.scraper import scrape_page
from app.services.analyzer import run_analysis
from app.services.llm import enhance_with_llm
from app.utils.helpers import is_email, parse_email

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="OSINT AI — Digital Intelligence Engine",
    description="Accepts name, username, or email. Search -> Scrape -> Analyze -> GPT-4o.",
    version="6.0.0",
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
        "version": "6.0.0",
        "llm_enabled": settings.llm_enabled,
        "model": settings.openai_model if settings.llm_enabled else "rule-based only",
    }


# ── SSE helper ────────────────────────────────────────────────────────────────

def _evt(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data)}\n\n"


# ── Streaming search endpoint (used by UI) ────────────────────────────────────

@app.get("/search/stream", tags=["osint"])
async def search_stream(
    query: str = Query(..., min_length=2, max_length=200)
):
    """
    Server-Sent Events endpoint.
    Emits real-time progress as each pipeline stage completes.
    """
    settings = get_settings()

    async def pipeline():
        # ── Email detection ───────────────────────────────────────
        email_meta_raw = None
        if is_email(query):
            email_meta_raw = await asyncio.to_thread(parse_email, query)
            yield _evt({"type": "email_detected", "meta": email_meta_raw})

        # ── Stage 1: Search ───────────────────────────────────────
        yield _evt({"type": "stage", "stage": "search",
                    "message": "Searching DuckDuckGo..."})

        urls = await asyncio.to_thread(fetch_search_urls, query)

        if not urls:
            yield _evt({"type": "error",
                        "message": "No search results found. Try a different query."})
            return

        yield _evt({"type": "stage_done", "stage": "search",
                    "message": f"Found {len(urls)} URLs"})

        # ── Stage 2: Scrape (per-URL progress) ───────────────────
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
                "type": "scrape_progress",
                "done": i + 1,
                "total": len(urls),
                "url": url,
                "success": ok,
            })

        if not scraped:
            yield _evt({"type": "error",
                        "message": "All pages failed to load."})
            return

        yield _evt({"type": "stage_done", "stage": "scrape",
                    "message": f"Scraped {len(scraped)} / {len(urls)} pages"})

        # ── Stage 3: Analysis ─────────────────────────────────────
        yield _evt({"type": "stage", "stage": "analyze",
                    "message": "Running rule-based analysis..."})

        rule_result = await asyncio.to_thread(
            run_analysis, query, scraped, email_meta_raw
        )

        yield _evt({"type": "stage_done", "stage": "analyze",
                    "message": (
                        f"{len(rule_result['profiles_found'])} profiles · "
                        f"{len(rule_result['entities'])} clusters · "
                        f"{len(rule_result['insights'])} insights"
                    )})

        # ── Stage 4: LLM ──────────────────────────────────────────
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

        # ── Final result ──────────────────────────────────────────
        llm_enhanced = llm_result is not None
        summary  = llm_result.get("summary")  if llm_enhanced else None
        insights = (llm_result.get("insights") or rule_result["insights"]) if llm_enhanced else rule_result["insights"]

        report = OSINTReport(
            query=query,
            llm_enhanced=llm_enhanced,
            summary=summary,
            email_meta=EmailMeta(**email_meta_raw) if email_meta_raw else None,
            profiles_found=rule_result["profiles_found"],
            ranked_sources=[RankedSource(**s) for s in rule_result["ranked_sources"]],
            entities=[Entity(**e)            for e in rule_result["entities"]],
            insights=insights,
        )

        yield _evt({"type": "result", "data": report.model_dump()})

    return StreamingResponse(
        pipeline(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── JSON endpoint (kept for API / curl usage) ─────────────────────────────────

@app.get("/search", response_model=OSINTReport, tags=["osint"])
async def search(
    query: str = Query(..., min_length=2, max_length=200)
):
    settings = get_settings()
    email_meta_raw = parse_email(query) if is_email(query) else None

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

    rule_result = await asyncio.to_thread(run_analysis, query, scraped, email_meta_raw)
    llm_result  = await asyncio.to_thread(enhance_with_llm, query, rule_result, scraped) \
                  if settings.llm_enabled else None

    llm_enhanced = llm_result is not None
    return OSINTReport(
        query=query,
        llm_enhanced=llm_enhanced,
        summary=llm_result.get("summary") if llm_enhanced else None,
        email_meta=EmailMeta(**email_meta_raw) if email_meta_raw else None,
        profiles_found=rule_result["profiles_found"],
        ranked_sources=[RankedSource(**s) for s in rule_result["ranked_sources"]],
        entities=[Entity(**e)            for e in rule_result["entities"]],
        insights=(llm_result.get("insights") or rule_result["insights"]) if llm_enhanced else rule_result["insights"],
    )
