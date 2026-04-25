import re
from urllib.parse import urlparse

# ── Text utilities ────────────────────────────────────────────────────────────

def clean_text(raw: str) -> str:
    """Remove excessive whitespace and non-printable characters."""
    text = re.sub(r"[ \t]+", " ", raw)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_url(url: str) -> str:
    """Lowercase scheme+host, strip trailing slash and fragments."""
    parsed = urlparse(url.strip())
    normalized = parsed._replace(fragment="", query="")
    return normalized.geturl().rstrip("/").lower()


def deduplicate_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for url in urls:
        key = normalize_url(url)
        if key not in seen:
            seen.add(key)
            result.append(url)
    return result


# ── Email utilities ───────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

# Known personal email providers
_PERSONAL_PROVIDERS = {
    "gmail.com", "yahoo.com", "yahoo.in", "hotmail.com", "outlook.com",
    "live.com", "icloud.com", "me.com", "mac.com", "protonmail.com",
    "proton.me", "zoho.com", "rediffmail.com", "ymail.com", "aol.com",
}

# Educational domain patterns
_EDU_PATTERNS = [".edu", ".ac.in", ".ac.uk", ".edu.in", ".ac.au"]


def is_email(query: str) -> bool:
    """Return True if the query string looks like an email address."""
    return bool(_EMAIL_RE.match(query.strip()))


def parse_email(email: str) -> dict:
    """
    Parse an email address into its components.

    Returns:
        {
            email, username, name_guess, domain,
            provider, account_type: personal | corporate | educational
        }
    """
    email   = email.strip().lower()
    local, domain = email.split("@", 1)

    # Clean username: remove +tag (john+spam@gmail → john)
    username = local.split("+")[0]

    # Guess human name: john.doe / john_doe → John Doe
    name_guess = re.sub(r"[._\-]+", " ", username).title()

    # Identify provider label
    provider_map = {
        "gmail.com": "Gmail", "yahoo.com": "Yahoo", "yahoo.in": "Yahoo",
        "hotmail.com": "Hotmail", "outlook.com": "Outlook", "live.com": "Outlook",
        "icloud.com": "iCloud", "me.com": "iCloud", "mac.com": "iCloud",
        "protonmail.com": "ProtonMail", "proton.me": "ProtonMail",
        "rediffmail.com": "Rediffmail", "zoho.com": "Zoho",
    }
    provider = provider_map.get(domain, domain)

    # Determine account type
    if domain in _PERSONAL_PROVIDERS:
        account_type = "personal"
    elif any(domain.endswith(p) for p in _EDU_PATTERNS):
        account_type = "educational"
    else:
        account_type = "corporate"

    return {
        "email":        email,
        "username":     username,
        "name_guess":   name_guess,
        "domain":       domain,
        "provider":     provider,
        "account_type": account_type,
    }
