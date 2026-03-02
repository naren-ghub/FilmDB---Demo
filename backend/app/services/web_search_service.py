
import httpx

from app.config import settings
from app.utils.tool_formatter import normalize_tool_output


async def run(query: str) -> dict:
    if not settings.SERPER_API_KEY:
        return normalize_tool_output("error", {"reason": "missing_serper_key"})

    headers = {
        "X-API-KEY": settings.SERPER_API_KEY,
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        try:
            resp = await client.post(
                "https://google.serper.dev/search", headers=headers, json={"q": query, "gl": "in"}
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return normalize_tool_output("error", {"query": query})

    organic = payload.get("organic") or []
    snippets = [item.get("snippet") for item in organic if item.get("snippet")]
    sources = [
        {"title": item.get("title"), "link": item.get("link")}
        for item in organic[:5]
        if item.get("title") and item.get("link")
    ]
    summary = " ".join(snippets[:3])

    data = {"query": query, "summary": summary, "sources": sources}
    return normalize_tool_output("success", data)
