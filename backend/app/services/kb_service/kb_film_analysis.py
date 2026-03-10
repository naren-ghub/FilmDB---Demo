"""KB Film Analysis — Scraped article retrieval from analysis_layer.jsonl."""

import logging
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

log = logging.getLogger(__name__)


async def run(title: str = "", person: str = "") -> dict[str, Any]:
    """
    Retrieve film analysis articles from the scraped analysis layer.
    Can search by movie title (resolved to IMDb ID) or by person name.
    """
    from rag.filmdb_query_engine import FilmDBQueryEngine

    engine = FilmDBQueryEngine.get_instance()

    results = []

    # Search by movie title → resolve to IMDb ID → analysis_search
    if title:
        imdb_id = engine.resolve_title_to_imdb_id(title)
        if imdb_id:
            results = engine.analysis_search(imdb_id, max_results=5)

    # Search by person name → analysis_search_by_person
    if person and not results:
        results = engine.analysis_search_by_person(person, max_results=5)

    if not results:
        return {
            "status": "not_found",
            "data": {"title": title, "person": person, "message": "No analysis articles found"},
        }

    # Format the output — include chunks for LLM grounding
    articles = []
    for r in results:
        article = {
            "source": r.get("source"),
            "knowledge_type": r.get("knowledge_type"),
            "title": r.get("title"),
            "author": r.get("author"),
            "url": r.get("url"),
            "text_preview": r.get("text_preview"),
        }
        # Include top chunks for RAG context (limit to keep token budget manageable)
        chunks = r.get("chunks", [])
        article["analysis_chunks"] = chunks[:3]
        articles.append(article)

    return {
        "status": "success",
        "data": {
            "query_title": title,
            "query_person": person,
            "article_count": len(articles),
            "articles": articles,
        },
    }
