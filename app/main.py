import asyncio
import json
import logging
import time
from collections import defaultdict
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from app.core.config import get_settings
from app.models.schemas import OSINTReport, Entity, RankedSource, EmailMeta, ConfirmedAccount, GoogleFootprint, HIBPResult, Breach, EmailRepResult
from app.services.search import fetch_search_urls
from app.services.scraper import scrape_page
from app.services.analyzer import run_analysis
from app.services.llm import enhance_with_llm
from app.services.holehe_checker import check_email as holehe_check, TOTAL_PLATFORMS
from app.services.google_footprint import find_google_footprint
from app.services.hibp_checker import check_breaches
from app.services.emailrep_checker import check_email_reputation
from app.utils.helpers import is_email, parse_email

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
    description="Accepts name, username, or email. Search -> Holehe -> Scrape -> Analyze -> GPT-4o.",
    version="8.1.0",
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
        "version": "8.1.0",
        "llm_enabled": settings.llm_enabled,
        "model": settings.openai_model if settings.llm_enabled else "rule-based only",
        "holehe_platforms": TOTAL_PLATFORMS,
        "hibp_enabled": settings.hibp_enabled,
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
        # ── Email detection ───────────────────────────────────────
        email_meta_raw  = None
        confirmed_raw   = []
        google_fp_raw   = None
        hibp_raw        = None
        emailrep_raw    = None

        if is_email(query):
            email_meta_raw = parse_email(query)
            yield _evt({"type": "email_detected", "meta": email_meta_raw})

            # ── Stage 0: Holehe (email only) ─────────────────────
            yield _evt({
                "type": "stage", "stage": "holehe",
                "message": f"Checking {TOTAL_PLATFORMS} platforms...",
                "total": TOTAL_PLATFORMS,
            })

            # Progress callback — yields an SSE event after each batch
            async def on_holehe_progress(checked, total, found):
                nonlocal confirmed_raw
                confirmed_raw = found
                yield_queue.append(_evt({
                    "type": "holehe_progress",
                    "checked": checked,
                    "total": total,
                    "found": len(found),
                    "latest": [r["name"] for r in found[-3:]],  # last 3 found
                }))

            # We can't yield inside a callback, so we use a queue
            yield_queue: list[str] = []

            confirmed_raw = await holehe_check(query, on_progress=on_holehe_progress)

            # Flush queued progress events
            for evt in yield_queue:
                yield evt

            yield _evt({
                "type": "stage_done", "stage": "holehe",
                "message": f"Found {len(confirmed_raw)} confirmed accounts on {TOTAL_PLATFORMS} platforms",
                "count": len(confirmed_raw),
            })

            # Emit each confirmed account so UI can show them as they arrive
            for acc in confirmed_raw:
                yield _evt({
                    "type": "confirmed_account",
                    "name": acc.get("name", ""),
                    "domain": acc.get("domain", ""),
                })
            # ── Stage 0b: Google Footprint ────────────────────────
            yield _evt({"type": "stage", "stage": "google",
                        "message": "Looking up Google account profile..."})
            google_fp_raw = await find_google_footprint(query)
            if google_fp_raw["found"]:
                yield _evt({
                    "type": "stage_done", "stage": "google",
                    "message": f"Google profile found (uid: {google_fp_raw['user_id']})",
                    "maps_url":   google_fp_raw["maps_url"],
                    "photos_url": google_fp_raw["photos_url"],
                    "user_id":    google_fp_raw["user_id"],
                })
            else:
                yield _evt({"type": "stage_skip", "stage": "google",
                            "message": "No public Google profile found"})

            # ── Stage 0c: HIBP breach check ───────────────────────
            if settings.hibp_enabled:
                yield _evt({"type": "stage", "stage": "hibp",
                            "message": "Checking Have I Been Pwned..."})
                hibp_raw = await check_breaches(query, settings.hibp_api_key)
                if not hibp_raw["ok"]:
                    yield _evt({"type": "stage_skip", "stage": "hibp",
                                "message": f"HIBP error: {hibp_raw['error']}"})
                elif hibp_raw["found"]:
                    yield _evt({
                        "type": "stage_done", "stage": "hibp",
                        "message": f"Found in {hibp_raw['count']} breach(es)!",
                        "count": hibp_raw["count"],
                        "severity": "high" if any(
                            b["severity"] == "high" for b in hibp_raw["breaches"]
                        ) else "medium",
                    })
                else:
                    yield _evt({"type": "stage_done", "stage": "hibp",
                                "message": "Clean — no breaches found"})
            else:
                yield _evt({"type": "stage_skip", "stage": "hibp",
                            "message": "No HIBP_API_KEY — skipped"})

            # ── Stage 0d: EmailRep (free, always runs for email) ──
            yield _evt({"type": "stage", "stage": "emailrep",
                        "message": "Checking email reputation (EmailRep.io)..."})
            emailrep_raw = await check_email_reputation(query)
            if not emailrep_raw["ok"]:
                yield _evt({"type": "stage_skip", "stage": "emailrep",
                            "message": emailrep_raw.get("error", "EmailRep unavailable")})
            else:
                leaked  = emailrep_raw["credentials_leaked"]
                breached = emailrep_raw["data_breach"]
                rep     = emailrep_raw["reputation"]
                yield _evt({
                    "type": "stage_done", "stage": "emailrep",
                    "message": (
                        f"Reputation: {rep}"
                        + (" · credentials leaked!" if leaked else "")
                        + (" · in data breach" if breached else "")
                        + (f" · {len(emailrep_raw['profiles'])} profiles known" if emailrep_raw["profiles"] else "")
                    ),
                })

        else:
            yield _evt({"type": "stage_skip", "stage": "holehe",
                        "message": "Email not detected — skipped"})
            yield _evt({"type": "stage_skip", "stage": "google",
                        "message": "Email not detected — skipped"})
            yield _evt({"type": "stage_skip", "stage": "hibp",
                        "message": "Email not detected — skipped"})
            yield _evt({"type": "stage_skip", "stage": "emailrep",
                        "message": "Email not detected — skipped"})

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

        # ── Stage 2: Scrape ───────────────────────────────────────
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
        summary  = llm_result.get("summary") if llm_enhanced else None
        insights = (llm_result.get("insights") or rule_result["insights"]) \
                   if llm_enhanced else rule_result["insights"]

        confirmed_accounts = [
            ConfirmedAccount(
                name=r.get("name", ""),
                domain=r.get("domain", ""),
            )
            for r in confirmed_raw
        ]

        hibp_result = None
        if hibp_raw:
            hibp_result = HIBPResult(
                ok=hibp_raw["ok"],
                found=hibp_raw["found"],
                count=hibp_raw["count"],
                breaches=[Breach(**b) for b in hibp_raw["breaches"]],
                error=hibp_raw.get("error"),
            )

        report = OSINTReport(
            query=query,
            llm_enhanced=llm_enhanced,
            summary=summary,
            email_meta=EmailMeta(**email_meta_raw) if email_meta_raw else None,
            confirmed_accounts=confirmed_accounts,
            google_footprint=GoogleFootprint(**google_fp_raw) if google_fp_raw else None,
            hibp_result=hibp_result,
            emailrep_result=EmailRepResult(**emailrep_raw) if emailrep_raw else None,
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
    settings        = get_settings()
    email_meta_raw  = parse_email(query) if is_email(query) else None
    confirmed_raw   = await holehe_check(query) if email_meta_raw else []
    google_fp_raw   = await find_google_footprint(query) if email_meta_raw else None
    hibp_raw        = await check_breaches(query, settings.hibp_api_key) \
                      if (email_meta_raw and settings.hibp_enabled) else None
    emailrep_raw    = await check_email_reputation(query) if email_meta_raw else None

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
        confirmed_accounts=[ConfirmedAccount(name=r.get("name",""), domain=r.get("domain",""))
                            for r in confirmed_raw],
        google_footprint=GoogleFootprint(**google_fp_raw) if google_fp_raw else None,
        hibp_result=HIBPResult(
            ok=hibp_raw["ok"], found=hibp_raw["found"], count=hibp_raw["count"],
            breaches=[Breach(**b) for b in hibp_raw["breaches"]], error=hibp_raw.get("error"),
        ) if hibp_raw else None,
        emailrep_result=EmailRepResult(**emailrep_raw) if emailrep_raw else None,
        profiles_found=rule_result["profiles_found"],
        ranked_sources=[RankedSource(**s) for s in rule_result["ranked_sources"]],
        entities=[Entity(**e) for e in rule_result["entities"]],
        insights=(llm_result.get("insights") or rule_result["insights"]) if llm_enhanced else rule_result["insights"],
    )
