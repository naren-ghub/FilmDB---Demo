import logging
import re
from difflib import get_close_matches
from typing import Any


_ALIAS_MAP = {
    "goodfells": "Goodfellas",
    "god father": "The Godfather",
    "godfather": "The Godfather",
    "the god father": "The Godfather",
    "piano teacher": "The Piano Teacher",
    "the piano teacher": "The Piano Teacher",
    "shawshank": "The Shawshank Redemption",
    "shawshank redemption": "The Shawshank Redemption",
    "dark knight": "The Dark Knight",
    "the dark knight": "The Dark Knight",
    "fight club": "Fight Club",
    "inception": "Inception",
    "interstellar": "Interstellar",
    "oscar 2026": "98th Academy Awards",
    "oscars 2026": "98th Academy Awards",
    "academy awards 2026": "98th Academy Awards",
}

_AWARD_KEYWORDS = ("oscar", "oscars", "academy awards", "nominations", "best picture","BAFTA")

# Phrases to strip from user messages to extract the actual movie/person name
_FILLER_PATTERNS = [
    r"^(?:tell me about|what (?:is|are)|show me|find|search for|look up|get|give me)\s+",
    r"^(?:who is|who are|who was)\s+",
    r"^(?:plot (?:summary|of)|summary of|synopsis of|overview of|details of|info on|information about)\s+",
    r"^(?:where can i (?:stream|watch)|stream|watch)\s+",
    r"^(?:movies? (?:similar|like) (?:to)?|similar (?:movies?|films?) (?:to|like)?)\s+",
    r"^(?:(?:is|are) .+ (?:available|streaming) (?:on|in)?)\s+",
    r"^(?:best (?:movies?|films?) (?:by|of|from))\s+",
    r"^(?:filmography (?:of|for)?|filmography)\s+",
    r"^(?:(?:top|best) (?:3|three|5|five|10|ten) (?:movies?|films?) (?:of|by|from)?)\s+",
    r"^(?:awards? (?:won |received )?(?:by|of|for)?)\s+",
    r"^(?:biography (?:of|for)?)\s+",
]

# Trailing noise to strip
_TRAILING_PATTERNS = [
    r"\s+(?:movie|film|series|show|documentary)$",
    r"\s+(?:in \w+|\d{4})$",
    r"\s*\?$",
]


def _normalize(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", text.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _extract_year(text: str) -> int | None:
    match = re.search(r"\b(18|19|20)\d{2}\b", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _clean_entity_from_message(text: str) -> str:
    """Strip common filler phrases to extract the core entity name from a message."""
    cleaned = text.strip()
    # Strip leading filler phrases (apply repeatedly to catch stacked patterns)
    for _ in range(3):
        prev = cleaned
        for pattern in _FILLER_PATTERNS:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
        if cleaned == prev:
            break
    # Strip trailing noise
    for pattern in _TRAILING_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()
    # Remove surrounding quotes
    if len(cleaned) > 2 and cleaned[0] in ('"', "'", "\u201c") and cleaned[-1] in ('"', "'", "\u201d"):
        cleaned = cleaned[1:-1].strip()
    return cleaned if cleaned else text.strip()


def _extract_candidate(message: str, intent: dict[str, Any]) -> str:
    entities = intent.get("entities", [])
    primary = intent.get("primary_intent", "")
    
    expected_type = None
    if primary in ("PERSON_LOOKUP", "FILMOGRAPHY"): expected_type = "person"
    elif primary in ("AWARD_LOOKUP",): expected_type = "award_event"
    elif primary in ("ENTITY_LOOKUP", "PLOT_EXPLANATION", "CRITIC_SUMMARY", "MOVIE_SIMILARITY", "COMPARISON", "REVIEWS", "ANALYTICAL_EXPLANATION", "RECOMMENDATION", "DOWNLOAD", "LEGAL_DOWNLOAD", "STREAMING_AVAILABILITY"):
        expected_type = "movie"

    valid_core_types = {"movie", "person", "award_event"}
    
    if entities:
        # First pass: try to match expected type
        for ent in entities:
            if isinstance(ent, dict):
                etype = ent.get("type", "").lower()
                val = ent.get("value")
                if expected_type and etype == expected_type and isinstance(val, str) and val.strip():
                    return val.strip()
                    
        # Second pass: fallback to any valid core type
        for ent in entities:
            if isinstance(ent, dict) and ent.get("type", "").lower() in valid_core_types:
                val = ent.get("value")
                if isinstance(val, str) and val.strip():
                    return val.strip()
            elif isinstance(ent, str) and ent.strip():
                return ent.strip()

    # Fallback: try to extract entity name from the raw message
    return _clean_entity_from_message(message)


def _infer_entity_type(message: str, intent: dict[str, Any]) -> str | None:
    primary = intent.get("primary_intent", "")
    if primary in ("PERSON_LOOKUP", "FILMOGRAPHY"):
        return "person"
    if primary in ("AWARD_LOOKUP",):
        return "award_event"
    if primary in ("TRENDING", "UPCOMING", "TOP_RATED", "STREAMING_DISCOVERY"):
        return "catalog"
    if primary in ("DOWNLOAD", "LEGAL_DOWNLOAD", "STREAMING_AVAILABILITY"):
        return "movie"
    if primary in ("ENTITY_LOOKUP", "PLOT_EXPLANATION", "CRITIC_SUMMARY",
                   "MOVIE_SIMILARITY", "COMPARISON", "REVIEWS",
                   "ANALYTICAL_EXPLANATION", "RECOMMENDATION"):
        return "movie"
    lowered = message.lower()
    if lowered.startswith("who is") or "biography" in lowered:
        return "person"
    if "movie" in lowered or "film" in lowered or "plot" in lowered or "rating" in lowered:
        return "movie"
    # Special case: Known name-like movie titles
    name_like_movies = {"marty supreme", "mary poppins", "the godfather", "john wick"}
    if _normalize(message) in name_like_movies:
        return "movie"
    return None


class EntityResolver:
    _log = logging.getLogger(__name__)

    def resolve(self, message: str, intent: dict[str, Any]) -> dict[str, Any]:
        normalized_message = _normalize(message)
        year = _extract_year(normalized_message)
        candidate = _extract_candidate(message, intent)
        normalized_candidate = _normalize(candidate)

        entity_type = _infer_entity_type(message, intent)
        if any(keyword in normalized_message for keyword in _AWARD_KEYWORDS):
            entity_type = "award_event"

        canonical = _ALIAS_MAP.get(normalized_candidate)
        if not canonical:
            matches = get_close_matches(normalized_candidate, _ALIAS_MAP.keys(), n=1, cutoff=0.88)
            if matches:
                canonical = _ALIAS_MAP.get(matches[0])

        entity_value = canonical or candidate
        canonical_id = None

        # Attempt imdb_id resolution via KB for movie entities
        if entity_type == "movie" and entity_value:
            canonical_id = self._resolve_imdb_id(entity_value, str(year) if year else None)

        public_domain = False
        if year is not None and year < 1928:
            public_domain = True

        return {
            "entity_value": entity_value,
            "entity_type": entity_type,
            "canonical_id": canonical_id,
            "year": year,
            "public_domain": public_domain,
        }

    def _resolve_imdb_id(self, title: str, year: str | None = None) -> str | None:
        """Try to resolve title to imdb_id via the FilmDB KB."""
        try:
            from rag.filmdb_query_engine import FilmDBQueryEngine
            engine = FilmDBQueryEngine.get_instance()
            return engine.resolve_title_to_imdb_id(title, year)
        except Exception as exc:
            self._log.debug("KB imdb_id resolution failed: %s", exc)
            return None
