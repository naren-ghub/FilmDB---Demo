"""KB Plot Analysis — Wikipedia plot retrieval from local Parquet KB."""

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
    Retrieve Wikipedia plot summary for a movie from the local KB.
    """
    from rag.filmdb_query_engine import FilmDBQueryEngine

    engine = FilmDBQueryEngine.get_instance()
    imdb_id = engine.resolve_title_to_imdb_id(title)
    if not imdb_id:
        return {"status": "not_found", "data": {"title": title}}

    result = engine.plot_analysis(imdb_id)
    if not result:
        return {"status": "not_found", "data": {"title": title, "imdb_id": imdb_id}}

    # Add movie title for context
    entity = engine.entity_lookup(imdb_id)
    if entity:
        result["title"] = entity.get("title")
        result["year"] = entity.get("year")
        result["genres"] = entity.get("genres")

    return {"status": "success", "data": result}
