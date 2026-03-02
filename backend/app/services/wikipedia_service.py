
import httpx

from app.config import settings
from app.utils.tool_formatter import normalize_tool_output


async def run(title: str) -> dict:
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        try:
            resp = await client.get(url)
            if resp.status_code == 404:
                return normalize_tool_output("not_found", {"title": title})
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return normalize_tool_output("error", {"title": title})

    data = {
        "title": payload.get("title") or title,
        "summary": payload.get("extract", ""),
        "thumbnail": (payload.get("thumbnail") or {}).get("source"),
    }
    return normalize_tool_output("success", data)
