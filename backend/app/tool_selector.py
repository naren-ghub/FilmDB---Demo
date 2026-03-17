# -*- coding: utf-8 -*-
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

@dataclass
class QueryProfile:
    """Structure to encapsulate the context of a query for deterministic routing."""
    entity_type: str = "unknown"       # e.g., "movie", "person", "concept"
    query_type: str = "general"        # e.g., "factual", "analytical", "conceptual", "recommendation"
    domain: Optional[str] = None       # e.g., "film_history", "film_criticism"
    secondary_domain: Optional[str] = None
    secondary_query_type: Optional[str] = None  # from secondary_intents[0]

# A static map to replace the complex intent-based RoutingMatrix
TOOL_GROUPS = {
    # Factual lookups for movies (metadata, plot, cast)
    "movie_factual": [
        "kb_entity",
        "kb_plot",
        "wikipedia",
        "tmdb_service",
        "imdb_awards",
    ],
    
    # Deep analytical queries about a movie's themes, cinematography, etc.
    "movie_analytical": [
        "rag_essays",
        "rag_books",
        "kb_plot",
    ],
    
    # Factual lookups for directors, actors, cinematographers
    "person_factual": [
        "kb_filmography",
        "wikipedia",
        "tmdb_service"
    ],
    
    # Abstract queries about film theory, movements, or history
    "conceptual": [
        "rag_books",
        "rag_essays"
    ],
    
    # Finding similar movies or curated lists
    "recommendation": [
        "kb_similarity",
        "tmdb_service",
        "top_rated_movies"
    ],
    
    # Querying where to watch a specific film
    "streaming": [
        "watchmode",
        "kb_entity"
    ],

    # Downloading a specific film
    "download": [
        "archive_service"
    ]
}

# Used to map historical or varied tool names to their canonical identifiers in the GovernanceRegistry
TOOL_ALIASES = {
    "kb_plot_analysis": "kb_plot",
    "wikipedia_service": "wikipedia",
    "rag_core": "rag_books"  # Example alias mapping
}

def map_intent_to_query_type(primary_intent: str) -> str:
    """Classifies a legacy semantic intent string into a structural query type."""
    pi = (primary_intent or "").upper()
    
    analytical_intents = {
        "FILM_ANALYSIS", "VISUAL_ANALYSIS", "THEORETICAL_ANALYSIS",
        "DIRECTOR_ANALYSIS", "STYLE_COMPARISON", "FILM_COMPARISON",
        "SCENE_ANALYSIS", "CHARACTER_ANALYSIS", "THEMATIC_ANALYSIS"
    }
    
    conceptual_intents = {
        "CONCEPTUAL_EXPLANATION", "MOVEMENT_OVERVIEW", "HISTORICAL_CONTEXT"
    }
    
    recommendation_intents = {
        "RECOMMENDATION", "TOP_RATED", "TRENDING", "UPCOMING"
    }

    streaming_intents = {
        "STREAMING_AVAILABILITY", "OTT_AVAILABILITY", "VOD_AVAILABILITY0",
        "VOD_AVAILABILITY","NETFLIX","HULU","AMAZON PRIME","DISNEY+","HBO MAX", "WHERE TO WATCH"
    }

    download_intents = {
        "DOWNLOAD", "DOWNLOAD_LINK", "LEGAL_DOWNLOAD", "ILLEGAL_DOWNLOAD_REQUEST", 
        "WATCH_FOR_FREE"
    }

    if pi in analytical_intents:
        return "analytical"
    elif pi in conceptual_intents:
        return "conceptual"
    elif pi in recommendation_intents:
        return "recommendation"
    elif pi == streaming_intents:
        return "availability"
    elif pi in download_intents:
        return "download"
    else:
        # Default to factual for ENTITY_LOOKUP, PERSON_LOOKUP, FILMOGRAPHY, etc.
        return "factual"

def select_tools(profile: QueryProfile) -> List[str]:
    """
    Selects the foundational tools required to answer a query based on its profile.
    This replaces the legacy Intent -> Tool routing.
    """
    tools = []
    
    # 1. Primary Entity Logic
    if profile.entity_type == "movie":
        if profile.query_type == "analytical":
            tools.extend(TOOL_GROUPS["movie_analytical"])
        elif profile.query_type == "recommendation":
            tools.extend(TOOL_GROUPS["recommendation"])
        elif profile.query_type == "availability":
            tools.extend(TOOL_GROUPS["streaming"])
        elif profile.query_type == "download":
            tools.extend(TOOL_GROUPS["download"])
            tools.extend(TOOL_GROUPS["streaming"])      # Needed for legal fallbacks
            tools.extend(TOOL_GROUPS["movie_factual"])  # Needed for release years and validity
        else:
            tools.extend(TOOL_GROUPS["movie_factual"])
            
    elif profile.entity_type == "person":
        tools.extend(TOOL_GROUPS["person_factual"])
        
    elif profile.entity_type == "concept" or profile.query_type == "conceptual":
        tools.extend(TOOL_GROUPS["conceptual"])
        
    else:
        # Fallback for completely unknown contexts
        tools.append("kb_entity")
        
    # 2. Secondary Domain Handling (Enrichment Hints)
    # If the classifier hinted at specific academic domains, we can inject RAG tools
    # without overriding the primary structural tools above.
    domain_hints = [profile.domain, profile.secondary_domain]
    injected_rag = False

    if "film_history" in domain_hints and "rag_books" not in tools:
        tools.append("rag_books")
        injected_rag = True
    if "film_criticism" in domain_hints and "rag_essays" not in tools:
        tools.append("rag_essays")
        injected_rag = True
    if "film_aesthetics" in domain_hints and "rag_books" not in tools:
        tools.append("rag_books")
        injected_rag = True
    if "film_production" in domain_hints:
        if "rag_books" not in tools: tools.append("rag_books")
        if "rag_scripts" not in tools: tools.append("rag_scripts")
        injected_rag = True
    if "film_theory" in domain_hints:
        if "rag_books" not in tools: tools.append("rag_books")
        if "rag_essays" not in tools: tools.append("rag_essays")
        injected_rag = True
    if "film_script" in domain_hints and "rag_scripts" not in tools:
        tools.append("rag_scripts")
        injected_rag = True

    # If we injected any semantic RAG tools due to a domain hint, 
    # we MUST ensure kb_entity is present if it's a movie query
    if injected_rag and profile.entity_type == "movie" and "kb_entity" not in tools:
        tools.append("kb_entity")

    # 3. Secondary Intent Handling
    # If the classifier detected a secondary intent (e.g., STREAMING_AVAILABILITY
    # alongside FILM_ANALYSIS), merge the tools for that intent too.
    if profile.secondary_query_type:
        sec_profile = QueryProfile(
            entity_type=profile.entity_type,
            query_type=profile.secondary_query_type,
            domain=profile.domain,
            secondary_domain=profile.secondary_domain,
        )
        secondary_tools = select_tools(sec_profile)
        for t in secondary_tools:
            if t not in tools:
                tools.append(t)

    # De-duplicate while preserving order
    seen = set()
    unique_tools = []
    for t in tools:
        if t not in seen:
            unique_tools.append(t)
            seen.add(t)
            
    return unique_tools

def normalize_tool_aliases(tools: List[str]) -> List[str]:
    """Ensures tool names match the Governance Registry IDs."""
    return [TOOL_ALIASES.get(t, t) for t in tools]
