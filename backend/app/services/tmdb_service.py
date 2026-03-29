"""
FilmDB – TMDB Service
======================
Fetches movie details, credits, and metadata from The Movie Database (TMDB) API.
Replaces the broken IMDb/RapidAPI service as primary movie data source.
"""

import httpx
import logging

from app.config import settings
from app.utils.tool_formatter import normalize_tool_output

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.themoviedb.org/3"
_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
_MAX_RETRIES = 2


async def _get(client: httpx.AsyncClient, path: str, params: dict | None = None) -> dict:
    """GET request to TMDB with retry logic."""
    url = f"{_BASE_URL}{path}"
    all_params = {"api_key": settings.TMDB_API_KEY}
    if params:
        all_params.update(params)

    last_error = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = await client.get(url, params=all_params)
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            last_error = f"timeout (attempt {attempt + 1})"
            logger.warning(f"TMDB timeout: {path} (attempt {attempt + 1})")
            continue
        except httpx.HTTPStatusError as e:
            if 400 <= e.response.status_code < 500:
                raise
            last_error = f"HTTP {e.response.status_code}"
            logger.warning(f"TMDB error: {path} - {last_error} (attempt {attempt + 1})")
            continue
        except Exception as e:
            last_error = str(e)
            logger.warning(f"TMDB error: {path} - {e} (attempt {attempt + 1})")
            continue
    raise httpx.ConnectError(f"All {_MAX_RETRIES + 1} attempts failed: {last_error}")


async def run(title: str, year: str | int | None = None) -> dict:
    """Search for a movie by title and return rich metadata."""
    if not settings.TMDB_API_KEY:
        return normalize_tool_output("error", {"reason": "missing_tmdb_api_key"})

    clean_title = title.strip()

    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        try:
            search_params = {
                "query": clean_title,
                "include_adult": "false",
                "language": "en-US",
                "page": 1,
            }
            if year:
                search_params["year"] = str(year)

            # Step 1: Search for the movie
            search_data = await _get(client, "/search/movie", search_params)
            results = search_data.get("results", [])
            
            # Disambiguation logic: If multiple hits exist with similar popularity or different years
            if not year and len(results) > 1:
                # Check for popular candidates (e.g. popularity > 5 or just top 3)
                candidates = []
                for r in results[:5]:
                    cand_year = (r.get("release_date") or "")[:4]
                    candidates.append({
                        "title": r.get("title"),
                        "year": cand_year,
                        "tmdb_id": r.get("id"),
                        "overview": r.get("overview", "")[:100] + "..."
                    })
                
                # If we have multiple significant results, we might want to disambiguate
                # LOWERED THRESHOLD: If results are somewhat popular or very similar in popularity
                if len(results) > 1:
                     p1 = results[0].get("popularity", 0)
                     p2 = results[1].get("popularity", 0)
                     # If the second hit is at least 30% as popular as the first, or both are popular
                     if p2 > 5 or (p1 > 0 and p2 / p1 > 0.3):
                         return normalize_tool_output("disambiguation", {
                             "title": clean_title,
                             "candidates": candidates,
                             "reason": "multiple_likely_matches"
                         })

            if not results and year:
                # Retry without year if no exact match
                search_params.pop("year")
                search_data = await _get(client, "/search/movie", search_params)
                results = search_data.get("results", [])

            if not results:
                return normalize_tool_output("not_found", {"title": clean_title})

            # Pick the best result
            movie = results[0]
            movie_id = movie.get("id")

            # Step 2: Get full details + credits + videos in one go
            details = await _get(client, f"/movie/{movie_id}", {
                "append_to_response": "credits,videos",
                "language": "en-US",
            })

        except httpx.HTTPStatusError as e:
            logger.error(f"TMDB HTTP error for '{clean_title}': {e.response.status_code}")
            return normalize_tool_output("error", {"title": clean_title, "reason": f"HTTP {e.response.status_code}"})
        except Exception as e:
            logger.error(f"TMDB service failed for '{clean_title}': {e}")
            return normalize_tool_output("error", {"title": clean_title, "reason": str(e)})

    # Extract structured data
    credits = details.get("credits", {})

    # Cast (top 10)
    cast = []
    for member in (credits.get("cast") or [])[:10]:
        name = member.get("name")
        if name:
            cast.append(name)

    # Directors
    directors = []
    for member in credits.get("crew") or []:
        if member.get("job") == "Director":
            name = member.get("name")
            if name:
                directors.append(name)

    # Genres
    genres = [g.get("name") for g in (details.get("genres") or []) if g.get("name")]

    # Poster
    poster_path = details.get("poster_path")
    poster_url = f"{_IMAGE_BASE}{poster_path}" if poster_path else None

    # Trailer key (YouTube via TMDB videos)
    videos = details.get("videos", {}).get("results", [])
    trailer = next(
        (v for v in videos if v.get("type") == "Trailer" and v.get("site") == "YouTube"),
        None,
    )
    trailer_key = trailer.get("key") if trailer else None

    # Rating
    rating = details.get("vote_average")
    if rating is not None:
        try:
            rating = round(float(rating), 1)
        except (ValueError, TypeError):
            rating = None

    data = {
        "title": details.get("title") or clean_title,
        "year": (details.get("release_date") or "")[:4] or None,
        "rating": rating,
        "rating_count": details.get("vote_count"),
        "cast": cast,
        "director": directors[0] if directors else None,
        "directors": directors,
        "plot": (details.get("overview") or "")[:500],
        "genres": genres,
        "poster_url": poster_url,
        "tmdb_id": movie_id,
        "imdb_id": details.get("imdb_id"),
        "runtime_minutes": details.get("runtime"),
        "tagline": details.get("tagline") or "",
        "status": details.get("status"),
        "original_language": details.get("original_language"),
        "trailer_key": trailer_key,
    }
    return normalize_tool_output("success", data)



async def get_person(name: str) -> dict:
    """Search for a person (actor/director) and return their details."""
    if not settings.TMDB_API_KEY:
        return normalize_tool_output("error", {"reason": "missing_tmdb_api_key"})

    clean_name = name.strip()

    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        try:
            # Search for the person
            search_data = await _get(client, "/search/person", {
                "query": clean_name,
                "language": "en-US",
                "page": 1,
            })
            results = search_data.get("results", [])
            if not results:
                return normalize_tool_output("not_found", {"name": clean_name})

            person = results[0]
            person_id = person.get("id")

            # Get full details + credits
            details = await _get(client, f"/person/{person_id}", {
                "append_to_response": "movie_credits",
                "language": "en-US",
            })

        except Exception as e:
            logger.error(f"TMDB person lookup failed for '{clean_name}': {e}")
            return normalize_tool_output("error", {"name": clean_name, "reason": str(e)})

    # Enhanced Filmography: Categorize by Role
    movie_credits = details.get("movie_credits", {})
    cast_credits = movie_credits.get("cast") or []
    crew_credits = movie_credits.get("crew") or []

    gender = details.get("gender") # 1=female, 2=male
    actor_role = "actress" if gender == 1 else "actor"

    filmography_by_role = {}
    
    # Process Cast
    for c in cast_credits:
        role = actor_role
        if role not in filmography_by_role: filmography_by_role[role] = []
        filmography_by_role[role].append({
            "title": c.get("title"),
            "year": (c.get("release_date") or "")[:4],
            "character": c.get("character"),
            "rating": round(c.get("vote_average", 0), 1),
            "vote_count": c.get("vote_count", 0),
            "tmdb_id": c.get("id")
        })

    # Process Crew
    for c in crew_credits:
        job = (c.get("job") or "unknown").lower()
        if job not in filmography_by_role: filmography_by_role[job] = []
        filmography_by_role[job].append({
            "title": c.get("title"),
            "year": (c.get("release_date") or "")[:4],
            "rating": round(c.get("vote_average", 0), 1),
            "vote_count": c.get("vote_count", 0),
            "tmdb_id": c.get("id")
        })

    # Sort each role by year descending
    for role in filmography_by_role:
        filmography_by_role[role].sort(key=lambda x: (x["year"] or "0", x["vote_count"]), reverse=True)

    # Simple flat filmography for backward compatibility and LLM summary
    flat_list = []
    seen = set()
    # Prioritize popular ones for the flat list
    all_credits = sorted(cast_credits + crew_credits, key=lambda x: x.get("vote_count", 0), reverse=True)
    for c in all_credits[:25]:
        t = c.get("title")
        if t and t not in seen:
            flat_list.append(t)
            seen.add(t)

    profile_path = details.get("profile_path")
    poster_url = f"{_IMAGE_BASE}{profile_path}" if profile_path else None

    data = {
        "name": details.get("name") or clean_name,
        "birth_date": details.get("birthday"),
        "death_date": details.get("deathday"),
        "profession": details.get("known_for_department"),
        "biography": (details.get("biography") or "")[:600],
        "known_for": flat_list[:10],
        "filmography": flat_list,
        "filmography_by_role": filmography_by_role,
        "poster_url": poster_url,
        "tmdb_id": person_id,
        "imdb_id": details.get("imdb_id"),
        "place_of_birth": details.get("place_of_birth"),
    }
    return normalize_tool_output("success", data)

