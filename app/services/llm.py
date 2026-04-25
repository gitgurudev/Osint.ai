"""
GPT-4o enhancement layer.
Takes rule-based OSINT output + scraped content → richer summary + insights.
Falls back gracefully if API key is missing or call fails.
"""

import json
import logging
from openai import OpenAI
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a senior OSINT analyst.
You will receive:
1. A search query (person or username being investigated)
2. Pre-analyzed rule-based findings (profiles, entities, signals)
3. Raw scraped content from search results

Your job: enrich the analysis with deeper insights.
Be factual. Never invent information not present in the provided content.
If data is insufficient, say so clearly."""

_RESPONSE_SCHEMA = """{
  "summary": "<2-3 sentence executive overview of who this person/entity is>",
  "insights": [
    "<specific, evidence-backed finding>",
    "<another insight>",
    "..."
  ]
}"""


def _build_context(
    query: str,
    rule_based: dict,
    scraped_content: str,
    content_limit: int,
) -> str:
    profiles   = rule_based.get("profiles_found", [])
    entities   = rule_based.get("entities", [])
    rb_insights = rule_based.get("insights", [])

    # Trim content to limit tokens and cost
    trimmed = scraped_content[:content_limit]

    return (
        f"SEARCH TARGET: {query}\n\n"
        f"--- Rule-based findings ---\n"
        f"Profiles found: {json.dumps(profiles)}\n"
        f"Entities: {json.dumps(entities)}\n"
        f"Initial insights:\n" + "\n".join(f"  - {i}" for i in rb_insights) + "\n\n"
        f"--- Scraped web content (trimmed to {content_limit} chars) ---\n"
        f"{trimmed}\n\n"
        f"Return ONLY valid JSON matching this schema:\n{_RESPONSE_SCHEMA}"
    )


def enhance_with_llm(
    query: str,
    rule_based: dict,
    scraped_pages: list[dict],
) -> dict | None:
    """
    Call GPT-4o to enrich rule-based OSINT output.

    Returns dict with keys: summary, insights
    Returns None on any failure (caller should fall back to rule-based).
    """
    settings = get_settings()

    if not settings.llm_enabled:
        logger.info("LLM disabled — OPENAI_API_KEY not set.")
        return None

    # Merge scraped content in credibility order (analyzer already sorted)
    merged = "\n\n".join(
        f"[{p['url']}]\n{p['content']}" for p in scraped_pages
    )

    user_message = _build_context(
        query, rule_based, merged, settings.llm_content_limit
    )

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        data = json.loads(response.choices[0].message.content)
        logger.info("LLM enhancement successful — model=%s", settings.openai_model)
        return data

    except Exception as exc:
        logger.error("LLM enhancement failed (falling back to rule-based): %s", exc)
        return None
