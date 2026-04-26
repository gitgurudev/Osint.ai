"""
Have I Been Pwned (HIBP) integration.
Checks if an email address appears in any known data breaches.

Requires a HIBP API key ($3.50/month at haveibeenpwned.com/API/Key).
Skipped gracefully when HIBP_API_KEY is not set.

API docs: https://haveibeenpwned.com/API/v3
"""

import logging
import httpx

logger = logging.getLogger(__name__)

HIBP_BASE    = "https://haveibeenpwned.com/api/v3"
USER_AGENT   = "OSINT-AI/8.0 (github.com/gitgurudev/Osint.ai)"
SEVERITY_CLASSES = {"Passwords", "Password hints", "Credit cards", "Bank account numbers",
                    "Social security numbers", "Passport numbers", "Private messages"}


async def check_breaches(email: str, api_key: str) -> dict:
    """
    Check HIBP for all breaches tied to this email.

    Returns:
        {
            "ok":       bool,           # False = API error
            "found":    bool,           # True = at least one breach
            "count":    int,
            "breaches": list[dict],     # sorted newest first
            "error":    str | None,
        }
    """
    headers = {
        "hibp-api-key": api_key,
        "User-Agent":   USER_AGENT,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{HIBP_BASE}/breachedaccount/{email}",
                params={"truncateResponse": "false"},
                headers=headers,
            )

        if resp.status_code == 404:
            logger.info("[HIBP] No breaches found for %s", email)
            return {"ok": True, "found": False, "count": 0, "breaches": [], "error": None}

        if resp.status_code == 401:
            logger.warning("[HIBP] Invalid API key")
            return {"ok": False, "found": False, "count": 0, "breaches": [],
                    "error": "Invalid HIBP API key. Check your HIBP_API_KEY in .env"}

        if resp.status_code == 429:
            logger.warning("[HIBP] Rate limited")
            return {"ok": False, "found": False, "count": 0, "breaches": [],
                    "error": "HIBP rate limit hit — try again in a moment"}

        if resp.status_code != 200:
            logger.warning("[HIBP] Unexpected status %d", resp.status_code)
            return {"ok": False, "found": False, "count": 0, "breaches": [],
                    "error": f"HIBP returned HTTP {resp.status_code}"}

        raw = resp.json()
        breaches = [_parse_breach(b) for b in raw]
        breaches.sort(key=lambda b: b["breach_date"], reverse=True)

        logger.info("[HIBP] %d breach(es) found for %s", len(breaches), email)
        return {"ok": True, "found": True, "count": len(breaches), "breaches": breaches, "error": None}

    except httpx.TimeoutException:
        return {"ok": False, "found": False, "count": 0, "breaches": [],
                "error": "HIBP request timed out"}
    except Exception as exc:
        logger.error("[HIBP] Unexpected error: %s", exc)
        return {"ok": False, "found": False, "count": 0, "breaches": [],
                "error": str(exc)}


def _parse_breach(b: dict) -> dict:
    data_classes = b.get("DataClasses", [])
    sensitive    = bool(SEVERITY_CLASSES & set(data_classes))
    return {
        "name":         b.get("Name", ""),
        "title":        b.get("Title", ""),
        "domain":       b.get("Domain", ""),
        "breach_date":  b.get("BreachDate", ""),
        "pwn_count":    b.get("PwnCount", 0),
        "data_classes": data_classes,
        "is_verified":  b.get("IsVerified", False),
        "is_sensitive": b.get("IsSensitive", False),
        "severity":     "high" if sensitive else "medium",
    }
