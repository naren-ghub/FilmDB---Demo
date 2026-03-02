
import httpx

from app.config import settings
from app.utils.tool_formatter import normalize_tool_output


async def run(title: str) -> dict:
    url = "https://archive.org/advancedsearch.php"
    query = f'title:({title}) AND mediatype:(movies)'
    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        try:
            resp = await client.get(url, params={"q": query, "output": "json"})
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return normalize_tool_output("error", {"title": title})

    docs = (payload.get("response") or {}).get("docs") or []
    if not docs:
        return normalize_tool_output("not_found", {"title": title, "download_link": ""})

    identifier = docs[0].get("identifier")
    if not identifier:
        return normalize_tool_output("not_found", {"title": title, "download_link": ""})

    link = f"https://archive.org/details/{identifier}"
    data = {"title": title, "download_link": link}
    return normalize_tool_output("success", data)
