"""KB Entity Lookup — Movie metadata from local Parquet KB."""

import logging
import sys
from pathlib import Path
from typing import Any

# Add project root so rag package is importable
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

log = logging.getLogger(__name__)


async def run(title: str) -> dict[str, Any]:
    """
    Lookup movie entity from the local KB.
    Returns enriched metadata (IMDb + TMDB + regional).
    """
    from rag.filmdb_query_engine import FilmDBQueryEngine

    engine = FilmDBQueryEngine.get_instance()
    imdb_id = engine.resolve_title_to_imdb_id(title)
    if not imdb_id:
        return {"status": "not_found", "data": {"title": title}}

    result = engine.entity_lookup(imdb_id)
    if not result:
        return {"status": "not_found", "data": {"title": title, "imdb_id": imdb_id}}

    # Enrich with local streaming availability
    streaming_info = engine.is_streaming(imdb_id)
    if streaming_info:
        result["streaming"] = streaming_info.get("platforms", [])
        result["age_rating"] = streaming_info.get("age_rating")
        result["is_tv_show"] = streaming_info.get("is_tv_show", False)

    return {"status": "success", "data": result}
