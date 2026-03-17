"""KB Compare — Semantic comparison between movies, people, or concepts from RAG."""

import logging
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

log = logging.getLogger(__name__)


async def run(concept_a: str, concept_b: str) -> dict[str, Any]:
    """
    Compare two conceptual entities (movies, people, concepts, decades, etc.)
    using semantic search over the film_criticism and analysis RAG layers.
    """
    from app.services.rag_service import RAGService
    
    if not concept_a.strip() or not concept_b.strip():
        return {
            "status": "error",
            "data": {"error": "Comparison requires two distinct concepts."}
        }
        
    rag = RAGService.get_instance()
    
    # We query the semantic layer with a combined contrast query
    query = f"Compare {concept_a} and {concept_b}"
    
    # Target our primary analytical datasets
    results = rag.query(
        query, 
        domains=["film_criticism", "analysis"],
        top_k=5
    )
    
    if not results:
        return {
            "status": "not_found",
            "data": {
                "concept_a": concept_a, 
                "concept_b": concept_b,
                "reason": "No deep analytical or critical comparison found in the knowledge base."
            }
        }
        
    return {
        "status": "success",
        "data": {
            "concept_a": concept_a,
            "concept_b": concept_b,
            "comparative_analysis": results
        }
    }
