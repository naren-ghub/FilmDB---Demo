
import httpx

from app.config import settings
from app.utils.tool_formatter import normalize_tool_output


def _pick_watchmode_id(payload: dict) -> int | None:
    results = payload.get("title_results") or payload.get("results") or []
    for item in results:
        if item.get("type") in ("movie", None):
            value = item.get("id")
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
    return None


async def run(title: str, region: str | None) -> dict:
    if not settings.WATCHMODE_API_KEY:
        return normalize_tool_output("error", {"reason": "missing_watchmode_key"})
    if not region:
        return normalize_tool_output("not_found", {"platforms": []})

    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        try:
            search_url = "https://api.watchmode.com/v1/search/"
            search_resp = await client.get(
                search_url,
                params={
                    "apiKey": settings.WATCHMODE_API_KEY,
                    "search_field": "name",
                    "search_value": title,
                },
            )
            search_resp.raise_for_status()
            watchmode_id = _pick_watchmode_id(search_resp.json())
            if not watchmode_id:
                return normalize_tool_output("not_found", {"platforms": []})

            sources_url = f"https://api.watchmode.com/v1/title/{watchmode_id}/sources/"
            sources_resp = await client.get(
                sources_url,
                params={"apiKey": settings.WATCHMODE_API_KEY, "regions": region},
            )
            sources_resp.raise_for_status()
            sources = sources_resp.json() or []
        except Exception:
            return normalize_tool_output("error", {"title": title, "region": region})

    platforms = []
    for source in sources:
        name = source.get("name") or source.get("source") or source.get("source_name")
        if name and name not in platforms:
            platforms.append(name)

    data = {"title": title, "region": region, "platforms": platforms}
    return normalize_tool_output("success", data)
