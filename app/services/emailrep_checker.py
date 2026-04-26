"""
EmailRep.io integration — free email reputation & breach signal check.
No API key required (10 req/hour free tier).
https://emailrep.io/
"""

import logging
import httpx

logger = logging.getLogger(__name__)

EMAILREP_URL = "https://emailrep.io/{email}"
USER_AGENT   = "OSINT-AI/8.0 (github.com/gitgurudev/Osint.ai)"

REPUTATION_ORDER = {"high": 3, "medium": 2, "low": 1, "none": 0}


async def check_email_reputation(email: str) -> dict:
    """
    Query EmailRep.io for reputation, breach signals, and known profiles.

    Returns:
        {
            "ok":                  bool,
            "reputation":          str,          # "high" | "medium" | "low" | "none"
            "suspicious":          bool,
            "references":          int,          # how many times seen on the internet
            "credentials_leaked":  bool,
            "credentials_leaked_recent": bool,
            "data_breach":         bool,
            "blacklisted":         bool,
            "spam":                bool,
            "free_provider":       bool,
            "deliverable":         bool,
            "first_seen":          str | None,
            "last_seen":           str | None,
            "profiles":            list[str],    # ["twitter", "spotify", ...]
            "error":               str | None,
        }
    """
    empty = _empty()
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get(
                EMAILREP_URL.format(email=email),
                headers={"User-Agent": USER_AGENT},
            )

        if r.status_code == 200:
            data    = r.json()
            details = data.get("details", {})
            result  = {
                "ok":                        True,
                "reputation":                data.get("reputation", "none"),
                "suspicious":                data.get("suspicious", False),
                "references":                data.get("references", 0),
                "credentials_leaked":        details.get("credentials_leaked", False),
                "credentials_leaked_recent": details.get("credentials_leaked_recent", False),
                "data_breach":               details.get("data_breach", False),
                "blacklisted":               details.get("blacklisted", False),
                "spam":                      details.get("spam", False),
                "free_provider":             details.get("free_provider", False),
                "deliverable":               details.get("deliverable", True),
                "first_seen":                details.get("first_seen"),
                "last_seen":                 details.get("last_seen"),
                "profiles":                  details.get("profiles", []),
                "error":                     None,
            }
            logger.info(
                "[EMAILREP] %s | reputation=%s | breached=%s | leaked=%s | profiles=%s",
                email, result["reputation"], result["data_breach"],
                result["credentials_leaked"], result["profiles"],
            )
            return result

        if r.status_code == 429:
            logger.warning("[EMAILREP] Rate limited")
            return {**empty, "error": "EmailRep rate limit — try again in an hour"}

        logger.warning("[EMAILREP] HTTP %d", r.status_code)
        return {**empty, "error": f"EmailRep returned HTTP {r.status_code}"}

    except httpx.TimeoutException:
        return {**empty, "error": "EmailRep timed out"}
    except Exception as exc:
        logger.error("[EMAILREP] %s", exc)
        return {**empty, "error": str(exc)}


def _empty() -> dict:
    return {
        "ok": False, "reputation": "none", "suspicious": False,
        "references": 0, "credentials_leaked": False,
        "credentials_leaked_recent": False, "data_breach": False,
        "blacklisted": False, "spam": False, "free_provider": False,
        "deliverable": True, "first_seen": None, "last_seen": None,
        "profiles": [], "error": None,
    }
