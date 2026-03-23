"""KB Awards Lookup — Local Oscar history from Parquet KB."""

import logging
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

log = logging.getLogger(__name__)

async def run(
    movie_title: str | None = None,
    person_name: str | None = None,
) -> dict[str, Any]:
    """
    Lookup Oscar awards and nominations for a movie or person.
    """
    from rag.engine.filmdb_query_engine import FilmDBQueryEngine

    engine = FilmDBQueryEngine.get_instance()
    
    if movie_title:
        imdb_id = engine.resolve_title_to_imdb_id(movie_title)
        if not imdb_id:
            return {"status": "not_found", "data": {"title": movie_title}}
            
        oscars = engine.get_movie_oscars(imdb_id)
        # Check fallback to person if title resolution yielded no oscars but it might be a person query mistakenly routed here
        if not oscars:
            return {"status": "success", "data": {"title": movie_title, "oscars": [], "message": "No Oscar nominations found for this film in the database."}}
            
        return {
            "status": "success",
            "data": {
                "title": movie_title,
                "imdb_id": imdb_id,
                "oscars": oscars,
                "total_nominations": len(oscars),
                "total_wins": sum(1 for o in oscars if o.get("won"))
            }
        }
        
    if person_name:
        # Resolve person name to nconst (currently fuzzy internal to engine, let's add a helper if needed, or query directly)
        nconst = engine._person_name_index.get(person_name.lower().strip())
        
        # Fuzzy fallback
        if not nconst:
            try:
                from rapidfuzz import fuzz, process as rfprocess
                candidates = list(engine._person_name_index.keys())
                if candidates:
                    match = rfprocess.extractOne(
                        person_name.lower().strip(), candidates, scorer=fuzz.ratio, score_cutoff=85
                    )
                    if match:
                        nconst = engine._person_name_index.get(match[0])
            except ImportError:
                pass
                
        if not nconst:
            return {"status": "not_found", "data": {"person_name": person_name}}
            
        oscars = engine.get_person_oscars(nconst)
        if not oscars:
             return {"status": "success", "data": {"person_name": person_name, "oscars": [], "message": "No Oscar nominations found for this person."}}
             
        return {
            "status": "success",
            "data": {
                "person_name": person_name,
                "nconst": nconst,
                "oscars": oscars,
                "total_nominations": len(oscars),
                "total_wins": sum(1 for o in oscars if o.get("won"))
            }
        }
        
    return {"status": "error", "message": "Must provide either movie_title or person_name"}
