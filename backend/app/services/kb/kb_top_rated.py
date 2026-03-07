"""KB Top Rated — Filtered ranking from local Parquet KB."""

import logging
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

log = logging.getLogger(__name__)


async def run(
    genre: str | None = None,
    year: str | None = None,
    language: str | None = None,
    count: int = 20,
) -> dict[str, Any]:
    """
    Return top-rated movies from the KB, with optional genre/year/language filters.
    Supports language-based filtering using the regional_layer (e.g. Tamil, Hindi).
    """
    from rag.filmdb_query_engine import FilmDBQueryEngine

    engine = FilmDBQueryEngine.get_instance()
    result = engine.top_rated(genre=genre, year=year, language=language, count=count)

    if not result.get("movies"):
        return {"status": "not_found", "data": {"genre": genre, "year": year, "language": language}}

    # Format for the response builder (match existing movie list format)
    movies = []
    for m in result["movies"]:
        movies.append({
            "title": m.get("title"),
            "year": m.get("year"),
            "rating": m.get("rating"),
            "imdb_id": m.get("imdb_id"),
        })

    return {
        "status": "success",
        "data": {
            "movies": movies,
            "filters": result.get("filters"),
            "count": result.get("count"),
        },
    }
