"""
Query Category Tracker — Lightweight Classification & Follow-up Generator
==========================================================================
Classifies each query into one of 4 knowledge categories and tracks session
coverage to generate contextual follow-up suggestions.

Categories:
    - narrative:  plot, story, scenes, characters, ending
    - analysis:   themes, symbolism, cinematography, direction, theory
    - factual:    cast, crew, rating, year, awards, box_office, runtime
    - discovery:  similar, recommend, trending, underrated, best, top
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Category Definitions ─────────────────────────────────────────────

KNOWLEDGE_CATEGORIES = {
    "narrative": [
        "plot", "story", "scene", "scenes", "character", "characters",
        "ending", "beginning", "twist", "storyline", "narrative",
        "what happens", "spoiler",
    ],
    "analysis": [
        "theme", "themes", "symbolism", "cinematography", "direction",
        "style", "theory", "visual", "meaning", "motif", "allegory",
        "subtext", "auteur", "mise-en-scene", "philosophy", "metaphor",
        "technique", "aesthetic", "analyze", "analyse", "interpretation",
        "depth", "critic", "review", "theory",
    ],
    "factual": [
        "cast", "crew", "rating", "year", "award", "awards", "oscar",
        "box office", "runtime", "director", "actor", "actress",
        "budget", "release", "producer", "writer", "imdb", "who played",
        "when was", "how much",
    ],
    "discovery": [
        "similar", "recommend", "recommendation", "trending", "underrated",
        "best", "top", "suggest", "like", "hidden gem", "must watch",
        "watchlist", "favorite", "upcoming",
    ],
}

# Map from intent to category (fast path)
_INTENT_CATEGORY_MAP = {
    # Analysis intents
    "FILM_ANALYSIS": "analysis",
    "VISUAL_ANALYSIS": "analysis",
    "CONCEPTUAL_EXPLANATION": "analysis",
    "DIRECTOR_ANALYSIS": "analysis",
    "THEORETICAL_ANALYSIS": "analysis",
    "STYLE_COMPARISON": "analysis",
    "HISTORICAL_CONTEXT": "analysis",
    "CRITIC_REVIEW": "analysis",
    "MOVEMENT_OVERVIEW": "analysis",
    # Factual intents
    "ENTITY_LOOKUP": "factual",
    "PERSON_LOOKUP": "factual",
    "FILMOGRAPHY": "factual",
    "AWARD_LOOKUP": "factual",
    "STREAMING_AVAILABILITY": "factual",
    # Narrative intents
    "PLOT_EXPLANATION": "narrative",
    # Discovery intents
    "RECOMMENDATION": "discovery",
    "TOP_RATED": "discovery",
    "TRENDING": "discovery",
    "COMPARISON": "analysis",
}

# User-friendly suggestions for each unexplored category
_CATEGORY_SUGGESTIONS = {
    "narrative": "Dive into its plot and story structure",
    "analysis": "Explore the themes and cinematic techniques",
    "factual": "Get the cast, ratings, and awards details",
    "discovery": "Find similar movies or curated recommendations",
}


def classify_query_category(message: str, primary_intent: str) -> str:
    """Zero-cost keyword + intent classifier. No LLM call needed.

    Returns one of: 'narrative', 'analysis', 'factual', 'discovery'.
    """
    # 1. Intent-based fast mapping (most reliable)
    if primary_intent in _INTENT_CATEGORY_MAP:
        return _INTENT_CATEGORY_MAP[primary_intent]

    # 2. Keyword fallback
    msg_lower = message.lower()
    scores: dict[str, int] = {cat: 0 for cat in KNOWLEDGE_CATEGORIES}

    for category, keywords in KNOWLEDGE_CATEGORIES.items():
        for kw in keywords:
            if kw in msg_lower:
                scores[category] += 1

    best = max(scores, key=lambda k: scores[k])
    if scores[best] > 0:
        return best

    return "factual"  # Safe default


def generate_followups(
    covered_categories: list[str],
    current_category: str,
    primary_entity: str | None = None,
) -> list[str]:
    """Generate 1-2 follow-up suggestions based on category gaps.

    Args:
        covered_categories: List of categories already explored in this session
        current_category: The category of the current query
        primary_entity: Optional entity name for personalized suggestions

    Returns:
        Up to 2 suggestion strings
    """
    all_categories = set(KNOWLEDGE_CATEGORIES.keys())
    covered = set(covered_categories) | {current_category}
    uncovered = all_categories - covered

    if not uncovered:
        return []

    suggestions = []
    entity_prefix = f"about {primary_entity}" if primary_entity else ""

    for cat in ["analysis", "discovery", "narrative", "factual"]:  # Priority order
        if cat in uncovered:
            base = _CATEGORY_SUGGESTIONS[cat]
            if entity_prefix:
                suggestions.append(f"{base} {entity_prefix}")
            else:
                suggestions.append(base)
            if len(suggestions) >= 2:
                break

    return suggestions


# ── Serialization helpers for session persistence ─────────────────────

def serialize_categories(categories: list[str]) -> str:
    """Serialize category list to JSON string for DB storage."""
    return json.dumps(list(set(categories)), ensure_ascii=False)


def deserialize_categories(raw: str | list | None) -> list[str]:
    """Deserialize category list from JSON string or list."""
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []

