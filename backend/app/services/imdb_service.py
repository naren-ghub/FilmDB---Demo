
import httpx
import logging
import re

from app.config import settings
from app.utils.tool_formatter import normalize_tool_output

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2


def _normalize_title(text: str) -> str:
    """Lowercase and strip non-alphanumeric for fuzzy comparison."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _pick_best_result(results: list, query_title: str) -> dict | None:
    """Pick the best matching result from IMDb search, preferring exact matches."""
    if not results:
        return None

    query_norm = _normalize_title(query_title)

    # First pass: exact match on primaryTitle
    for result in results[:20]:
        result_title = result.get("primaryTitle") or result.get("originalTitle") or ""
        if _normalize_title(result_title) == query_norm:
            return result

    # Second pass: query contained in title or vice versa
    for result in results[:20]:
        result_title = result.get("primaryTitle") or result.get("originalTitle") or ""
        result_norm = _normalize_title(result_title)
        if query_norm in result_norm or result_norm in query_norm:
            return result

    # Third pass: prefer movies over other types
    for result in results[:10]:
        if result.get("type") == "movie":
            return result

    # Fallback: first result
    return results[0] if results else None


def _extract_from_result(result: dict) -> dict:
    """Extract structured movie data from an imdb236 search result."""
    if not isinstance(result, dict):
        return {}

    # Rating
    rating = result.get("averageRating")
    if rating is not None:
        try:
            rating = float(rating)
        except (ValueError, TypeError):
            rating = None

    # Cast from description (imdb236 search doesn't return cast directly)
    cast = []
    directors = []

    # Genres
    genres = result.get("genres", []) or []

    # Poster
    poster_url = result.get("primaryImage")
    if isinstance(poster_url, dict):
        poster_url = poster_url.get("url")

    # Plot/description
    plot = result.get("description") or ""

    return {
        "title": result.get("primaryTitle") or result.get("originalTitle"),
        "year": result.get("startYear"),
        "rating": rating,
        "rating_count": result.get("numVotes"),
        "cast": cast,
        "director": directors[0] if directors else None,
        "directors": directors,
        "plot": plot[:500] if isinstance(plot, str) else "",
        "genres": genres,
        "poster_url": poster_url,
        "imdb_url": result.get("url"),
        "content_rating": result.get("contentRating"),
        "runtime_minutes": result.get("runtimeMinutes"),
    }


async def _request_with_retry(client: httpx.AsyncClient, url: str, headers: dict, params: dict) -> httpx.Response:
    """Make an HTTP GET with retry logic for transient failures."""
    last_error = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return resp
        except httpx.TimeoutException:
            last_error = f"timeout (attempt {attempt + 1})"
            logger.warning(f"IMDb API timeout: {url} (attempt {attempt + 1})")
            continue
        except httpx.HTTPStatusError as e:
            if 400 <= e.response.status_code < 500:
                raise
            last_error = f"HTTP {e.response.status_code} (attempt {attempt + 1})"
            logger.warning(f"IMDb API error: {url} - {last_error}")
            continue
        except Exception as e:
            last_error = str(e)
            logger.warning(f"IMDb API error: {url} - {e} (attempt {attempt + 1})")
            continue
    raise httpx.ConnectError(f"All {_MAX_RETRIES + 1} attempts failed: {last_error}")


async def run(title: str) -> dict:
    """Fetch movie details from IMDb via imdb236 API."""
    if not settings.RAPIDAPI_KEY:
        return normalize_tool_output("error", {"reason": "missing_rapidapi_key"})

    clean_title = title.strip()
    # Use imdb236 host (the imdb8 host returns 403)
    host = settings.IMDB236_HOST
    headers = {
        "X-RapidAPI-Key": settings.RAPIDAPI_KEY,
        "X-RapidAPI-Host": host,
    }

    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        try:
            # Search for the title
            search_url = f"https://{host}/api/imdb/search"
            search_resp = await _request_with_retry(
                client, search_url, headers,
                {"query": clean_title, "rows": 10}
            )
            search_data = search_resp.json()
            results = search_data.get("results", [])
            best = _pick_best_result(results, clean_title)
            if not best:
                return normalize_tool_output("not_found", {"title": clean_title})
        except Exception as e:
            logger.error(f"IMDb service failed for '{clean_title}': {e}")
            return normalize_tool_output("error", {"title": clean_title, "reason": str(e)})

    data = _extract_from_result(best)
    data["imdb_id"] = best.get("id")
    data["title"] = data.get("title") or clean_title
    return normalize_tool_output("success", data)
