import logging
from fastapi import FastAPI, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.core.config import get_settings
from app.models.schemas import OSINTReport, Entity, RankedSource, EmailMeta
from app.services.search import fetch_search_urls
from app.services.scraper import scrape_urls
from app.services.analyzer import run_analysis
from app.services.llm import enhance_with_llm
from app.utils.helpers import is_email, parse_email

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="OSINT AI — Digital Intelligence Engine",
    description=(
        "Accepts name, username, or email address.\n"
        "Search -> Scrape -> Rule-based analysis -> GPT-4o enhancement.\n"
        "Add OPENAI_API_KEY to .env for LLM-enhanced reports."
    ),
    version="5.0.0",
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
        "service": "OSINT AI",
        "version": "5.0.0",
        "llm_enabled": settings.llm_enabled,
        "model": settings.openai_model if settings.llm_enabled else "rule-based only",
        "accepts": "name | username | email",
    }


@app.get("/search", response_model=OSINTReport, tags=["osint"])
def search(
    query: str = Query(
        ...,
        min_length=2,
        max_length=200,
        description="Person name, username, or email address to investigate",
    )
):
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("[REQUEST] query=%r", query)

    # ── Detect email input ────────────────────────────────────────────────────
    email_meta_raw = None
    if is_email(query):
        email_meta_raw = parse_email(query)
        logger.info(
            "[REQUEST] Email detected | name_guess=%r | type=%s | provider=%s",
            email_meta_raw["name_guess"],
            email_meta_raw["account_type"],
            email_meta_raw["provider"],
        )

    # ── 1. Search ─────────────────────────────────────────────────────────────
    urls = fetch_search_urls(query)
    logger.info("[PIPELINE] Search done | urls_found=%d", len(urls))
    if not urls:
        logger.error("[PIPELINE] FAILED at search — no URLs returned")
        raise HTTPException(
            status_code=404,
            detail="No search results found. Try a more specific query.",
        )

    # ── 2. Scrape ─────────────────────────────────────────────────────────────
    scraped = scrape_urls(urls)
    logger.info("[PIPELINE] Scrape done | pages=%d / %d", len(scraped), len(urls))
    if not scraped:
        logger.error("[PIPELINE] FAILED at scrape — all pages empty")
        raise HTTPException(
            status_code=502,
            detail="All pages failed to load. Check your network connection.",
        )

    # ── 3. Rule-based analysis ────────────────────────────────────────────────
    rule_result = run_analysis(query, scraped, email_meta=email_meta_raw)
    logger.info(
        "[PIPELINE] Analysis done | profiles=%d | entities=%d | insights=%d",
        len(rule_result["profiles_found"]),
        len(rule_result["entities"]),
        len(rule_result["insights"]),
    )

    # ── 4. GPT-4o enhancement ─────────────────────────────────────────────────
    settings = get_settings()
    logger.info("[PIPELINE] LLM=%s | model=%s", settings.llm_enabled, settings.openai_model)
    llm_result = enhance_with_llm(query, rule_result, scraped)
    logger.info("[PIPELINE] LLM=%s", "SUCCESS" if llm_result else "SKIPPED/FAILED")

    # ── 5. Merge ──────────────────────────────────────────────────────────────
    llm_enhanced = llm_result is not None
    summary  = llm_result.get("summary") if llm_enhanced else None
    insights = llm_result.get("insights", rule_result["insights"]) if llm_enhanced else rule_result["insights"]
    logger.info("[PIPELINE] Complete | llm_enhanced=%s", llm_enhanced)

    return OSINTReport(
        query=query,
        llm_enhanced=llm_enhanced,
        summary=summary,
        email_meta=EmailMeta(**email_meta_raw) if email_meta_raw else None,
        profiles_found=rule_result["profiles_found"],
        ranked_sources=[RankedSource(**s) for s in rule_result["ranked_sources"]],
        entities=[Entity(**e) for e in rule_result["entities"]],
        insights=insights,
    )
