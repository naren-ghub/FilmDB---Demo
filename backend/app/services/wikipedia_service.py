
import httpx
import urllib.parse
import logging

from app.config import settings
from app.utils.tool_formatter import normalize_tool_output

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2

# Wikipedia REST API requires a User-Agent header
_HEADERS = {
    "User-Agent": "FilmDB-Demo/1.0 (https://github.com/filmdb; filmdb@example.com)",
    "Accept": "application/json",
}


async def run(title: str) -> dict:
    clean_title = title.strip()
    # URL-encode the title so spaces and special chars don't break the URL
    encoded_title = urllib.parse.quote(clean_title, safe="")
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded_title}"

    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        last_error = None
        payload = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await client.get(url, headers=_HEADERS)
                if resp.status_code == 404:
                    # Try with "(film)" disambiguation suffix
                    if attempt == 0:
                        alt_title = urllib.parse.quote(f"{clean_title} (film)", safe="")
                        alt_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{alt_title}"
                        resp = await client.get(alt_url, headers=_HEADERS)
                        if resp.status_code == 404:
                            # Try title-cased version
                            tc_title = urllib.parse.quote(clean_title.title(), safe="")
                            tc_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{tc_title}"
                            resp = await client.get(tc_url, headers=_HEADERS)
                            if resp.status_code == 404:
                                return normalize_tool_output("not_found", {"title": clean_title})
                    else:
                        return normalize_tool_output("not_found", {"title": clean_title})
                resp.raise_for_status()
                payload = resp.json()
                break
            except httpx.TimeoutException:
                last_error = "timeout"
                logger.warning(f"Wikipedia timeout for '{clean_title}' (attempt {attempt + 1})")
                continue
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Wikipedia error for '{clean_title}' (attempt {attempt + 1}): {e}")
                continue
        else:
            return normalize_tool_output("error", {"title": clean_title, "reason": last_error})

    if not payload:
        return normalize_tool_output("error", {"title": clean_title, "reason": "empty response"})

    data = {
        "title": payload.get("title") or clean_title,
        "summary": payload.get("extract", ""),
        "thumbnail": (payload.get("thumbnail") or {}).get("source"),
    }
    return normalize_tool_output("success", data)
