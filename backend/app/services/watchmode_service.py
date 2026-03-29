
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


async def run(title: str, region: str | None = "IN") -> dict:
    """
    Search for a movie, find where it's streaming, and fetch deep metadata.
    Prioritizes India (IN) region by default.
    """
    if not settings.WATCHMODE_API_KEY:
        return normalize_tool_output("error", {"reason": "missing_watchmode_key"})
    
    # Ensure region is set (defaulting to India)
    target_region = region if region else "IN"

    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        try:
            # 1. Search for the title ID
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
                return normalize_tool_output("not_found", {"title": title, "platforms": []})

            # 2. Fetch Title Details (for trailer, rating, scores)
            details_url = f"https://api.watchmode.com/v1/title/{watchmode_id}/details/"
            details_resp = await client.get(
                details_url,
                params={"apiKey": settings.WATCHMODE_API_KEY}
            )
            details_resp.raise_for_status()
            details = details_resp.json()

            # 3. Fetch Sources (for streaming links and logos)
            sources_url = f"https://api.watchmode.com/v1/title/{watchmode_id}/sources/"
            sources_params = {"apiKey": settings.WATCHMODE_API_KEY}
            if target_region:
                sources_params["regions"] = target_region
                
            sources_resp = await client.get(sources_url, params=sources_params)
            sources_resp.raise_for_status()
            sources_list = sources_resp.json() or []
            
        except Exception as e:
            logger.error(f"Watchmode API error for '{title}': {e}")
            return normalize_tool_output("error", {"title": title, "region": target_region, "reason": str(e)})

    # 4. Process Streaming Platforms
    platforms = []
    seen_sources = set()
    for source in sources_list:
        source_name = source.get("name") or source.get("source_name")
        if not source_name or source_name in seen_sources:
            continue
            
        platforms.append({
            "name": source_name,
            "url": source.get("web_url"), # Direct movie link
            "format": source.get("format"), # HD, SD, 4K
            "type": source.get("type"),     # sub, rent, buy
            "price": source.get("price"),
            "logo": f"https://cdn.watchmode.com/provider_logos/{source.get('source_id')}_100.png" # Standard logo size
        })
        seen_sources.add(source_name)

    # 5. Build Final Response
    data = {
        "title": details.get("title") or title,
        "year": details.get("year"),
        "region": target_region,
        "us_rating": details.get("us_rating"),
        "critic_score": details.get("critic_score"),
        "user_rating": details.get("user_rating"),
        "relevance_score": details.get("relevance_score"),
        "trailer_url": details.get("trailer"), # Direct YouTube trailer
        "web_url": details.get("url"),         # Watchmode title page
        "description": details.get("plot_overview"),
        "platforms": platforms
    }
    
    return normalize_tool_output("success", data)

