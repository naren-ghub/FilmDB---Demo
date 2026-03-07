"""KB Movie Similarity — Tag-based recommendations from local Parquet KB."""

import logging
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

log = logging.getLogger(__name__)


async def run(title: str) -> dict[str, Any]:
    """
    Find similar movies based on shared MovieLens user-generated tags.
    Returns up to 10 movies with overlapping tags.
    """
    from rag.filmdb_query_engine import FilmDBQueryEngine

    engine = FilmDBQueryEngine.get_instance()
    imdb_id = engine.resolve_title_to_imdb_id(title)
    if not imdb_id:
        return {"status": "not_found", "data": {"title": title}}

    result = engine.movie_similarity(imdb_id)
    if not result:
        return {"status": "not_found", "data": {"title": title, "imdb_id": imdb_id}}

    # Format recommendations list for the response builder
    recs = result.get("recommendations", [])
    rec_titles = [r.get("title", "Unknown") for r in recs if r.get("title")]
    result["recommendation_titles"] = rec_titles

    return {"status": "success", "data": result}
