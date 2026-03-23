
import httpx

from app.config import settings
from app.utils.tool_formatter import normalize_tool_output


async def run(title: str) -> dict:
    url = "https://archive.org/advancedsearch.php"
    # Try exact title phrase, title terms, or general text matching, and sort by downloads to get the most relevant/popular hit
    # Prioritize exact title matches and filter for feature films/classic cinema collections
    query = f'title:("{title}") AND mediatype:(movies)'
    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        try:
            resp = await client.get(url, params={
                "q": query, 
                "output": "json",
                "sort[]": "downloads desc",
                "rows": "10",
                "fl[]": "identifier,title,collection,mediatype"
            })
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return normalize_tool_output("error", {"title": title})

    docs = (payload.get("response") or {}).get("docs") or []
    if not docs:
        return normalize_tool_output("not_found", {"title": title, "download_link": ""})

    # Pick the best candidate:
    # 1. Not a trailer/clip
    # 2. Prefer collections like 'feature_films', 'classic_cinema', 'scifi_horror'
    best_doc = None
    for doc in docs:
        t = doc.get("title", "").lower()
        if any(x in t for x in ["trailer", "teaser", "clip", "promo", "preview"]):
            continue
        
        collections = doc.get("collection") or []
        if isinstance(collections, str): collections = [collections]
        
        if any(c in collections for c in ["feature_films", "classic_cinema", "scifi_horror", "prelinger"]):
            best_doc = doc
            break
            
    # Fallback to the first non-trailer if no preferred collection found
    if not best_doc:
        for doc in docs:
            t = doc.get("title", "").lower()
            if not any(x in t for x in ["trailer", "teaser", "clip", "promo", "preview"]):
                best_doc = doc
                break

    # Absolute fallback
    if not best_doc:
        best_doc = docs[0]

    identifier = best_doc.get("identifier")
    link = f"https://archive.org/details/{identifier}"
    data = {"title": title, "download_link": link}
    return normalize_tool_output("success", data)
