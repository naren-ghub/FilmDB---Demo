"""KB Movie Comparison — Side-by-side movie data from local Parquet KB."""

import logging
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

log = logging.getLogger(__name__)


async def run(title_a: str, title_b: str) -> dict[str, Any]:
    """
    Compare two movies: both entities + plots + critic summaries side-by-side.
    """
    from rag.filmdb_query_engine import FilmDBQueryEngine

    engine = FilmDBQueryEngine.get_instance()

    # Resolve both titles
    imdb_a = engine.resolve_title_to_imdb_id(title_a)
    imdb_b = engine.resolve_title_to_imdb_id(title_b)

    if not imdb_a and not imdb_b:
        return {
            "status": "not_found",
            "data": {"title_a": title_a, "title_b": title_b},
        }

    result = engine.compare_movies(
        imdb_a or "unknown",
        imdb_b or "unknown",
    )

    if not result:
        return {
            "status": "not_found",
            "data": {"title_a": title_a, "title_b": title_b},
        }

    return {"status": "success", "data": result}
