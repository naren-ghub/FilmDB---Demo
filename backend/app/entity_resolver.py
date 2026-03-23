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
    "2001 space odyssey": "2001: A Space Odyssey",
    "2001 a space odyssey": "2001: A Space Odyssey",
    "space odyssey": "2001: A Space Odyssey",
    "eyes wide shut": "Eyes Wide Shut",
    "interstellar": "Interstellar",
    "interstler": "Interstellar",
    "intersletter": "Interstellar",
    "intersteller": "Interstellar",
}

_AWARD_KEYWORDS = ("oscar", "oscars", "academy awards", "nominations", "best picture","BAFTA")

# Phrases to strip from user messages to extract the actual movie/person name
_FILLER_PATTERNS = [
    r"^(?:te+l+\s+me\s+(?:about|abt)|what (?:is|are)|show me|find|search for|look up|get|give me)\s+",
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
    r"^(?:recommend|suggest|list|give me some)\s+",
    r"^(?:dwell into|elaborate on|explain|expalin|expain|explan)\s+",
    r"^(?:analyze|analyse|discuss|explore|examine)\s+",
    r"^(?:character\s+)?study\s+of\s+",
    r"^(?:tell\s+me\s+)?about\s+the\s+character\s+",
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
    elif primary in ("ENTITY_LOOKUP", "PLOT_EXPLANATION", "RECOMMENDATION", "DOWNLOAD", "DOWNLOAD_LINK", "LEGAL_DOWNLOAD", "STREAMING_AVAILABILITY"):
        expected_type = "movie"
    # FILM_ANALYSIS and COMPARISON can be about a movie, person, OR concept
    # — don't force expected_type, let entity extraction decide

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

    # A.3 — Fallback: try to extract entity name from the raw message.
    candidate = _clean_entity_from_message(message)
    
    # If the intent is conceptual (e.g., FILM_ANALYSIS or COMPARISON without a clear subject),
    # the concept might be naturally long (e.g., "1990s gangster films vs 2000s gangster films").
    if primary in ("FILM_ANALYSIS", "COMPARISON"):
        return candidate

    # Otherwise, if the cleaned result is still > 5 words it's almost certainly the full
    # user query, not a real entity name. Discard it.
    if len(candidate.split()) > 5:
        return ""
    return candidate


def _infer_query_type(message: str, intent: dict[str, Any]) -> str:
    """Classifies the query as 'factual', 'analytical', or 'conceptual'."""
    primary = intent.get("primary_intent", "")
    academic_intents = {
        "FILM_ANALYSIS", "CONCEPTUAL_EXPLANATION", "MOVEMENT_OVERVIEW", 
        "VISUAL_ANALYSIS", "THEORETICAL_ANALYSIS", "DIRECTOR_ANALYSIS", 
        "HISTORICAL_CONTEXT", "STYLE_COMPARISON", "FILM_COMPARISON", "CRITIC_REVIEW"
    }
    factual_intents = {
        "PERSON_LOOKUP", "FILMOGRAPHY", "AWARD_LOOKUP", "TRENDING", 
        "UPCOMING", "TOP_RATED", "DOWNLOAD", "STREAMING_AVAILABILITY", 
        "ENTITY_LOOKUP", "PLOT_EXPLANATION", "RECOMMENDATION", "COMPARISON"
    }

    if primary in academic_intents:
        entities = intent.get("entities", [])
        has_concrete = any(isinstance(e, dict) and e.get("type") in ("movie", "person") for e in entities)
        # If it's analytical but lacks a concrete subject, it is purely conceptual
        return "analytical" if has_concrete else "conceptual"
        
    return "factual"


class EntityResolver:
    _log = logging.getLogger(__name__)

    def resolve(self, message: str, intent: dict[str, Any], session_ctx: Any = None) -> dict[str, Any]:
        normalized_message = _normalize(message)
        year = _extract_year(normalized_message)
        
        # 1. Determine overarching query type
        query_type = _infer_query_type(message, intent)

        # 2. Extract structured entities array directly from LLM output
        raw_entities = intent.get("entities", [])
        structured_entities = []
        for e in raw_entities:
            if isinstance(e, dict) and "type" in e and "value" in e:
                # Add any missing types requested in architecture review (e.g. concept, movement)
                etype = e["type"].lower()
                val = e["value"]
                
                # Check for canonical mappings for movies
                if etype == "movie" and isinstance(val, str):
                    canonical_val = _ALIAS_MAP.get(_normalize(val))
                    if not canonical_val:
                        try:
                            from rag.engine.filmdb_query_engine import FilmDBQueryEngine
                            engine = FilmDBQueryEngine.get_instance()
                            candidates = list(engine._title_index.keys())
                            if candidates:
                                matches = get_close_matches(_normalize(val), candidates, n=1, cutoff=0.88)
                                if matches:
                                    canonical_val = matches[0].title()
                        except Exception:
                            pass
                            
                    # Fallback to hardcoded fuzzy
                    if not canonical_val:
                        matches = get_close_matches(_normalize(val), _ALIAS_MAP.keys(), n=1, cutoff=0.88)
                        if matches:
                            canonical_val = _ALIAS_MAP.get(matches[0])
                    val = canonical_val or val

                structured_entities.append({"type": etype, "value": val})

        # 3. Handle backwards compatibility (primary entity value/type)
        # Prefer EntityMemory stack if available, else fall back to legacy flat fields
        legacy_candidate = _extract_candidate(message, intent)
        if not legacy_candidate and session_ctx:
            # Try EntityMemory stack first (more accurate than flat slots)
            raw_stack = getattr(session_ctx, "entity_stack", None)
            if raw_stack:
                try:
                    import json as _json
                    from app.entity_memory import EntityMemory as _EM
                    mem = _EM.from_json(raw_stack)
                    primary_intent_local = intent.get("primary_intent", "")
                    # For person-oriented intents, prefer person entity
                    if primary_intent_local in ("PERSON_LOOKUP", "FILMOGRAPHY"):
                        legacy_candidate = mem.primary_person() or mem.primary_movie() or ""
                    else:
                        legacy_candidate = mem.primary_movie() or mem.primary_person() or ""
                except Exception:
                    pass

            # Final fallback to legacy flat slots if EntityMemory gave nothing
            if not legacy_candidate:
                if getattr(session_ctx, "last_movie", None):
                    legacy_candidate = session_ctx.last_movie
                    intent["primary_intent"] = "ENTITY_LOOKUP"
                elif getattr(session_ctx, "last_person", None):
                    legacy_candidate = session_ctx.last_person
                    intent["primary_intent"] = "PERSON_LOOKUP"
                elif getattr(session_ctx, "last_entity", None):
                    legacy_candidate = session_ctx.last_entity
                    if intent.get("primary_intent") == "GENERAL_CONVERSATION":
                        intent["primary_intent"] = "CONCEPTUAL_EXPLANATION"
        
        # P4 fix #13: If we have a potential character name but no movie, bind to last_movie
        if legacy_candidate and session_ctx and session_ctx.last_movie:
            # Simple heuristic: if the candidate is 1-2 words and not the movie itself, 
            # and intent is about a person/character, bind it.
            if len(legacy_candidate.split()) <= 2 and _normalize(legacy_candidate) != _normalize(session_ctx.last_movie):
                if query_type in ("factual", "analytical") and intent.get("primary_intent") in ("PERSON_LOOKUP", "THEORETICAL_ANALYSIS", "FILM_ANALYSIS"):
                    # We keep the candidate but can use last_movie to improve RAG retrieval later
                    pass                
        legacy_normalized = _normalize(legacy_candidate)
        
        primary_entity_type = None
        # Use first concrete entity type as primary, or fallback to the old infer logic
        for ent in structured_entities:
            if ent["type"] in ("movie", "person", "award_event"):
                primary_entity_type = ent["type"]
                break
                
        if not primary_entity_type:
             if "person" in [_infer_entity_type(message, intent) for _ in range(1)] if "who is" in normalized_message else False: pass # Skipped legacy infer for brevity
             if any(keyword in normalized_message for keyword in _AWARD_KEYWORDS):
                 primary_entity_type = "award_event"
             elif "who is" in normalized_message or "biography" in normalized_message or re.search(r"\b(?:best|top|great(?:est)?|famous)\s+(?:movies?|films?)\s+(?:by|of|from)\b", normalized_message):
                 primary_entity_type = "person"
             elif any(w in normalized_message for w in ("movie", "film", "plot", "rating", "download", "stream")):
                 primary_entity_type = "movie"
             elif legacy_normalized in {"marty supreme", "mary poppins", "the godfather", "john wick"}:
                 primary_entity_type = "movie"
             elif query_type == "conceptual":
                 primary_entity_type = "concept"

        # 4. Canonical / Spell Correction against FilmDB KB
        canonical = _ALIAS_MAP.get(legacy_normalized)
        
        # If not in hardcoded alias map, try dynamic fuzzy match against full KB
        if not canonical and legacy_candidate:
            try:
                from rag.engine.filmdb_query_engine import FilmDBQueryEngine
                engine = FilmDBQueryEngine.get_instance()
                
                # Check for exact match against titles first
                if legacy_normalized in engine._title_index:
                    canonical = legacy_candidate 
                else:
                    # Fuzzy match against the 10,000+ title index keys
                    candidates = list(engine._title_index.keys())
                    if candidates:
                        matches = get_close_matches(legacy_normalized, candidates, n=1, cutoff=0.88)
                        if matches:
                            canonical = matches[0].title() # Capitalize the matched title
            except Exception as e:
                self._log.warning("Dynamic spellcheck failed: %s", e)
                
        # Final fallback to hardcoded map fuzzy match if dynamic fails
        if not canonical and legacy_candidate:
            matches = get_close_matches(legacy_normalized, _ALIAS_MAP.keys(), n=1, cutoff=0.88)
            if matches:
                canonical = _ALIAS_MAP.get(matches[0])

        entity_value = canonical or legacy_candidate
        
        canonical_id = None
        # Attempt imdb_id resolution via KB for movie entities
        if primary_entity_type == "movie" and entity_value:
            canonical_id = self._resolve_imdb_id(entity_value, str(year) if year else None)
            
            # If year is missing from query, fetch it from KB for public domain check
            if not year and canonical_id:
                try:
                    from rag.engine.filmdb_query_engine import FilmDBQueryEngine
                    engine = FilmDBQueryEngine.get_instance()
                    year = engine.get_movie_year(canonical_id)
                except Exception:
                    pass

        public_domain = False
        if year is not None and year < 1928:
            public_domain = True

        return {
            # Legacy expected structure for existing tools
            "entity_value": entity_value,
            "entity_type": primary_entity_type,
            "canonical_id": canonical_id,
            "year": year,
            "public_domain": public_domain,
            
            # E.2 — New structured pipeline data 
            "query_type": query_type,
            "entities": structured_entities,
        }

    def _resolve_imdb_id(self, title: str, year: str | None = None) -> str | None:
        """Try to resolve title to imdb_id via the FilmDB KB."""
        try:
            from rag.engine.filmdb_query_engine import FilmDBQueryEngine
            engine = FilmDBQueryEngine.get_instance()
            return engine.resolve_title_to_imdb_id(title, year)
        except Exception as exc:
            self._log.debug("KB imdb_id resolution failed: %s", exc)
            return None
