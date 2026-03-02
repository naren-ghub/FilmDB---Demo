import httpx

from app.config import settings
from app.utils.tool_formatter import normalize_tool_output


def _normalize_movie(item: dict, source: str) -> dict:
    title = (
        item.get("title")
        or item.get("name")
        or item.get("originalTitle")
        or item.get("primaryTitle")
    )
    year = item.get("year") or item.get("releaseYear") or item.get("startYear")
    rating = (
        item.get("rating")
        or item.get("imdbRating")
        or item.get("ratingValue")
        or item.get("averageRating")
    )
    poster = None
    image = item.get("image") or item.get("poster") or item.get("primaryImage")
    if isinstance(image, dict):
        poster = image.get("url") or image.get("imageUrl")
    elif isinstance(image, str):
        poster = image

    return {
        "title": title,
        "year": year,
        "rating": rating,
        "poster_url": poster,
        "source": source,
    }


def _extract_items(payload: dict | list) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("results", "items", "movies", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


async def _fetch_list(path: str, params: dict | None = None) -> dict:
    if not settings.RAPIDAPI_KEY:
        return normalize_tool_output("error", {"reason": "missing_rapidapi_key"})
    if not path:
        return normalize_tool_output("error", {"reason": "missing_imdb_path"})

    headers = {
        "X-RapidAPI-Key": settings.RAPIDAPI_KEY,
        "X-RapidAPI-Host": settings.IMDB236_HOST,
    }
    url = f"https://{settings.IMDB236_HOST}{path}"
    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        try:
            resp = await client.get(url, headers=headers, params=params or {})
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return normalize_tool_output("error", {"path": path})

    items = _extract_items(payload)
    if not items:
        return normalize_tool_output("not_found", {"movies": []})

    movies = [_normalize_movie(item, "imdb") for item in items if isinstance(item, dict)]
    movies = [m for m in movies if m.get("title")]
    return normalize_tool_output("success", {"movies": movies})


async def run_trending_tamil() -> dict:
    return await _fetch_list(settings.IMDB_TRENDING_TAMIL_PATH)


async def run_top_rated_english() -> dict:
    return await _fetch_list(settings.IMDB_TOP_RATED_PATH)


async def run_upcoming(country: str | None = None) -> dict:
    params = {}
    if country:
        params["country"] = country
    return await _fetch_list(settings.IMDB_UPCOMING_PATH, params=params)
