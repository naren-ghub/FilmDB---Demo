
import httpx

from app.config import settings
from app.utils.tool_formatter import normalize_tool_output


async def _tmdb_similar(title: str) -> dict | None:
    if not settings.TMDB_API_KEY:
        return None
    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        try:
            search_resp = await client.get(
                "https://api.themoviedb.org/3/search/movie",
                params={"api_key": settings.TMDB_API_KEY, "query": title},
            )
            search_resp.raise_for_status()
            results = (search_resp.json() or {}).get("results") or []
            if not results:
                return None
            movie_id = results[0].get("id")
            if not movie_id:
                return None

            similar_resp = await client.get(
                f"https://api.themoviedb.org/3/movie/{movie_id}/similar",
                params={"api_key": settings.TMDB_API_KEY},
            )
            similar_resp.raise_for_status()
            similar_results = (similar_resp.json() or {}).get("results") or []
        except Exception:
            return None

    recommendations = [item.get("title") for item in similar_results if item.get("title")]
    return {"recommendations": recommendations}


async def _rapidapi_similar(imdb_id: str) -> dict | None:
    if not settings.RAPIDAPI_KEY:
        return None
    headers = {
        "X-RapidAPI-Key": settings.RAPIDAPI_KEY,
        "X-RapidAPI-Host": settings.SIMILARITY_HOST,
    }
    url = f"https://{settings.SIMILARITY_HOST}/similar/{imdb_id}"
    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return None

    recs = []
    for item in payload.get("results", []) or payload.get("similar", []) or []:
        title = item.get("title") or item.get("name")
        if title:
            recs.append(title)
    return {"recommendations": recs}


async def run(title: str, imdb_id: str | None = None) -> dict:
    tmdb_result = await _tmdb_similar(title)
    if tmdb_result is not None:
        return normalize_tool_output("success", {"title": title, **tmdb_result})

    if imdb_id:
        rapidapi_result = await _rapidapi_similar(imdb_id)
        if rapidapi_result is not None:
            return normalize_tool_output("success", {"title": title, **rapidapi_result})

    return normalize_tool_output("not_found", {"title": title})
