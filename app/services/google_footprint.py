"""
Google Footprint finder — discovers public Google account artifacts linked to an email.

Two methods (tried in order):
  1. Picasa/Google+ legacy API  → returns numeric user ID
  2. DuckDuckGo search fallback → scans for google.com/maps/contrib URLs

Once we have the user ID we can construct:
  - Google Maps reviews URL
  - Google Maps photos URL
"""

import re
import logging
import httpx
from typing import Optional

logger = logging.getLogger(__name__)

MAPS_REVIEWS = "https://www.google.com/maps/contrib/{uid}/reviews"
MAPS_PHOTOS  = "https://www.google.com/maps/contrib/{uid}/photos"
UID_RE       = re.compile(r"google\.com/maps/contrib/(\d{10,25})")


async def find_google_footprint(email: str) -> dict:
    """
    Returns:
        {
            "found":      bool,
            "user_id":    str | None,
            "maps_url":   str | None,
            "photos_url": str | None,
        }
    """
    uid = await _uid_via_picasa(email) or await _uid_via_search(email)

    if uid:
        logger.info("[GOOGLE] uid=%s found for %s", uid, email)
        return {
            "found":      True,
            "user_id":    uid,
            "maps_url":   MAPS_REVIEWS.format(uid=uid),
            "photos_url": MAPS_PHOTOS.format(uid=uid),
        }

    logger.info("[GOOGLE] No Google profile found for %s", email)
    return {"found": False, "user_id": None, "maps_url": None, "photos_url": None}


async def _uid_via_picasa(email: str) -> Optional[str]:
    """
    Old Picasa/Google Photos data API still returns a JSON response with
    the numeric Google account ID for public accounts.
    """
    url = f"https://picasaweb.google.com/data/entry/api/user/{email}"
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            r = await client.get(
                url,
                params={"alt": "json"},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
        if r.status_code == 200:
            data = r.json()
            uid = (
                data.get("entry", {})
                    .get("gphoto$user", {})
                    .get("$t")
            )
            if uid and str(uid).isdigit():
                return str(uid)
            # Also try gphoto$user in alternate locations
            uid2 = (
                data.get("entry", {})
                    .get("id", {})
                    .get("$t", "")
            )
            m = re.search(r"/(\d{10,25})$", uid2)
            if m:
                return m.group(1)
    except Exception as exc:
        logger.debug("[GOOGLE/PICASA] %s", exc)
    return None


async def _uid_via_search(email: str) -> Optional[str]:
    """
    DuckDuckGo fallback: search for google.com/maps/contrib pages
    mentioning the username or exact email.
    """
    try:
        from ddgs import DDGS
        username = email.split("@")[0]
        queries = [
            f'site:google.com/maps/contrib "{username}"',
            f'"{email}" site:google.com/maps',
            f'"{username}" google maps reviews contributor',
        ]
        with DDGS() as ddgs:
            for q in queries:
                results = list(ddgs.text(q, max_results=5))
                for r in results:
                    m = UID_RE.search(r.get("href", "") + " " + r.get("body", ""))
                    if m:
                        return m.group(1)
    except Exception as exc:
        logger.debug("[GOOGLE/SEARCH] %s", exc)
    return None
