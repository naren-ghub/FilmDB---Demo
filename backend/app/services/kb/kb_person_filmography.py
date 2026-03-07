"""KB Person Filmography — Person lookup from pre-built person_index.parquet."""

import logging
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

log = logging.getLogger(__name__)


async def run(name: str) -> dict[str, Any]:
    """
    Lookup person filmography from the pre-built person_index.
    Returns name, professions, and list of films with roles and ratings.
    """
    from rag.filmdb_query_engine import FilmDBQueryEngine

    engine = FilmDBQueryEngine.get_instance()
    result = engine.person_filmography(name)
    if not result:
        return {"status": "not_found", "data": {"name": name}}

    return {"status": "success", "data": result}
