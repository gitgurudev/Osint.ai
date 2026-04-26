"""
Holehe integration — direct platform registration-endpoint checking.
Only runs when input is an email address.
121 platforms checked in parallel batches.
"""

import asyncio
import logging
import httpx
from holehe.core import get_functions, import_submodules

logger = logging.getLogger(__name__)

# Load all holehe modules once at import time (expensive, do it once)
_MODS  = import_submodules("holehe.modules")
_FUNCS = get_functions(_MODS)

TOTAL_PLATFORMS = len(_FUNCS)
CHUNK_SIZE      = 20          # how many platforms to check per batch
REQUEST_TIMEOUT = 15          # seconds per HTTP request


async def check_email(
    email: str,
    on_progress=None,   # async callable(checked, total, new_found) or None
) -> list[dict]:
    """
    Check email against all holehe platforms.

    Args:
        email:       Email address to investigate.
        on_progress: Optional async callback called after each batch.
                     Signature: on_progress(checked: int, total: int, found: list[dict])

    Returns:
        List of dicts where exists=True:
        [{"name": "GitHub", "domain": "github.com", "exists": True, ...}, ...]
    """
    limits  = httpx.Limits(max_connections=50, max_keepalive_connections=20)
    timeout = httpx.Timeout(REQUEST_TIMEOUT)

    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        out: list[dict] = []

        for i in range(0, TOTAL_PLATFORMS, CHUNK_SIZE):
            chunk = _FUNCS[i : i + CHUNK_SIZE]

            # Run this batch in parallel; holehe modules handle their own errors
            await asyncio.gather(
                *[_safe_call(f, email, client, out) for f in chunk],
                return_exceptions=True,
            )

            checked    = min(i + CHUNK_SIZE, TOTAL_PLATFORMS)
            found_now  = [r for r in out if r.get("exists")]

            logger.info(
                "[HOLEHE] Batch done | checked=%d/%d | found=%d",
                checked, TOTAL_PLATFORMS, len(found_now),
            )

            if on_progress:
                await on_progress(checked, TOTAL_PLATFORMS, found_now)

    confirmed = [r for r in out if r.get("exists")]
    logger.info("[HOLEHE] Complete | confirmed=%d / %d platforms", len(confirmed), TOTAL_PLATFORMS)
    return confirmed


async def _safe_call(func, email, client, out):
    """Run a holehe module, swallow any exception so one failure doesn't kill the batch."""
    try:
        await func(email, client, out)
    except Exception as exc:
        logger.debug("[HOLEHE] Module %s failed: %s", func.__name__, exc)
