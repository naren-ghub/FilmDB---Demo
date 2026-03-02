
import httpx

from app.config import settings
from app.utils.tool_formatter import normalize_tool_output


def _pick_imdb_id(payload: dict) -> str | None:
    if not payload:
        return None
    results = payload.get("results")
    if isinstance(results, list) and results:
        first = results[0]
        imdb_id = first.get("id") or first.get("tconst")
        if isinstance(imdb_id, str):
            return imdb_id
    if isinstance(payload.get("id"), str):
        return payload.get("id")
    return None


def _extract_overview(payload: dict) -> dict:
    title_data = payload.get("title", {}) if isinstance(payload, dict) else {}
    ratings = payload.get("ratings", {}) if isinstance(payload, dict) else {}
    credits = payload.get("credits", {}) if isinstance(payload, dict) else {}

    cast = []
    for member in credits.get("cast", []) or []:
        name = member.get("name")
        if name:
            cast.append(name)

    directors = []
    for member in credits.get("director", []) or []:
        name = member.get("name")
        if name:
            directors.append(name)

    return {
        "title": title_data.get("title") or payload.get("titleText") or payload.get("title"),
        "year": title_data.get("year") or payload.get("year"),
        "rating": ratings.get("rating"),
        "cast": cast,
        "director": directors[0] if directors else None,
        "poster_url": (title_data.get("image") or {}).get("url"),
    }


async def run(title: str) -> dict:
    if not settings.RAPIDAPI_KEY:
        return normalize_tool_output("error", {"reason": "missing_rapidapi_key"})

    headers = {
        "X-RapidAPI-Key": settings.RAPIDAPI_KEY,
        "X-RapidAPI-Host": settings.IMDB_HOST,
    }

    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        try:
            find_url = f"https://{settings.IMDB_HOST}/title/find"
            find_resp = await client.get(find_url, headers=headers, params={"q": title})
            find_resp.raise_for_status()
            imdb_id = _pick_imdb_id(find_resp.json())
            if not imdb_id:
                return normalize_tool_output("not_found", {"title": title})

            overview_url = f"https://{settings.IMDB_HOST}/title/get-overview-details"
            overview_resp = await client.get(
                overview_url, headers=headers, params={"tconst": imdb_id}
            )
            overview_resp.raise_for_status()
            overview = overview_resp.json()
        except Exception:
            return normalize_tool_output("error", {"title": title})

    data = _extract_overview(overview)
    data["imdb_id"] = imdb_id
    data["title"] = data.get("title") or title
    return normalize_tool_output("success", data)
