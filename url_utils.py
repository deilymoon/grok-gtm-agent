"""URL validation helpers for live evidence sources."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Host fragments that are clearly fabricated placeholders
_FAKE_HOST_MARKERS = (
    "example.com",
    "example.org",
    "example.net",
    "placeholder",
    "yourcompany",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "invalid",
    "fake-url",
    "not-a-real",
)



def sanitize_url(url: str | None) -> str | None:
    """Strip citation glue / trailing punctuation from model or tool URLs."""
    if not url or not isinstance(url, str):
        return None
    u = url.strip()
    # Drop markdown / footnote glue stuck to the URL
    u = re.split(r"[\]\s]", u, maxsplit=1)[0]
    u = re.sub(r"\)\[\[.*$", "", u)
    u = re.sub(r"[\]\[\(\)\.,;:]+$", "", u)
    u = u.strip()
    return u or None


def validate_url(url: str | None, *, require_network: bool = False, timeout: float = 3.0) -> bool:
    """Return True if url looks like a real http(s) source URL.

    Best-effort: well-formed http(s) with a reasonable host passes. Optional
    HEAD/GET check when require_network=True; network failures do not reject a
    well-formed citation URL (prefer keeping xAI tool citations).
    """
    if not url or not isinstance(url, str):
        return False
    u = url.strip()
    if not u or " " in u or "\n" in u or "\t" in u:
        return False
    if not (u.startswith("http://") or u.startswith("https://")):
        return False
    try:
        parsed = urlparse(u)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower().strip(".")
    if not host or "." not in host:
        return False
    if any(m in host for m in _FAKE_HOST_MARKERS):
        return False
    # Reject bare TLDs / nonsense
    if len(host) < 4:
        return False
    if require_network:
        try:
            import httpx

            with httpx.Client(follow_redirects=True, timeout=timeout) as client:
                try:
                    r = client.head(u)
                    if r.status_code < 400 or r.status_code in {401, 403, 405}:
                        return True
                except Exception:
                    pass
                try:
                    r = client.get(u)
                    if r.status_code < 400 or r.status_code in {401, 403, 405}:
                        return True
                except Exception:
                    # Keep well-formed citation URLs when network check fails
                    return True
        except Exception:
            return True
    return True


def dedupe_urls(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in urls:
        u = sanitize_url(raw)
        if not u:
            continue
        key = u.rstrip("/").lower()
        if key in seen:
            continue
        if not validate_url(u):
            continue
        seen.add(key)
        out.append(u)
    return out
