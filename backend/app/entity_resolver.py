import re
from difflib import get_close_matches
from typing import Any


_ALIAS_MAP = {
    "goodfells": "Goodfellas",
    "god father": "The Godfather",
    "godfather": "The Godfather",
    "the god father": "The Godfather",
    "oscar 2026": "98th Academy Awards",
    "oscars 2026": "98th Academy Awards",
    "academy awards 2026": "98th Academy Awards",
}

_AWARD_KEYWORDS = ("oscar", "oscars", "academy awards", "nominations", "best picture")


def _normalize(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\\s]", " ", text.lower())
    cleaned = re.sub(r"\\s+", " ", cleaned).strip()
    return cleaned


def _extract_year(text: str) -> int | None:
    match = re.search(r"\\b(18|19|20)\\d{2}\\b", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _extract_candidate(message: str, intent: dict[str, Any]) -> str:
    entities = intent.get("entities", [])
    if entities:
        first = entities[0]
        if isinstance(first, dict):
            value = first.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()
        if isinstance(first, str) and first.strip():
            return first.strip()
    return message.strip()


def _infer_entity_type(message: str, intent: dict[str, Any]) -> str | None:
    primary = intent.get("primary_intent", "")
    if primary in ("PERSON_LOOKUP",):
        return "person"
    if primary in ("AWARD_LOOKUP",):
        return "award_event"
    if primary in ("TRENDING", "UPCOMING", "TOP_RATED", "STREAMING_DISCOVERY"):
        return "catalog"
    if primary in ("DOWNLOAD", "LEGAL_DOWNLOAD", "STREAMING_AVAILABILITY"):
        return "movie"
    lowered = message.lower()
    if lowered.startswith("who is") or "biography" in lowered:
        return "person"
    if "movie" in lowered or "film" in lowered or "plot" in lowered or "rating" in lowered:
        return "movie"
    return None


class EntityResolver:
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
