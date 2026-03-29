"""
C.2 — Sub-Intent Agents (one per domain)
=========================================
Each agent receives a narrow, specialized system prompt covering only its domain's intents.
This ensures:
1. Low token count.
2. Contextual Focus: The LLM is "aware" of its domain because it's initialized as e.g. a "Film Theory expert".
3. High Accuracy: Prevents the LLM from hallucinating intents from other domains.
Each agent class exposes:
    classify(message, llm) -> dict with keys:
        primary_intent, secondary_intents, entities, confidence
"""

from __future__ import annotations
import json
import logging
import re

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Shared JSON parser (reused by all agents)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_json(content: str | None, default: dict) -> dict:
    if not content:
        return default
    try:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        data = json.loads(match.group(0) if match else content)
        if not isinstance(data, dict):
            return default
        # Normalise confidence: float 0-1 → int 0-100
        c = data.get("confidence", 80)
        if isinstance(c, float) and 0 < c <= 1:
            c = int(c * 100)
        data["confidence"] = int(c) if isinstance(c, (int, float)) else 80
        return data
    except (json.JSONDecodeError, AttributeError):
        logger.debug("Sub-intent JSON parse failed: %s", content)
        return default


def _base_default(intent: str) -> dict:
    return {
        "primary_intent": intent,
        "secondary_intents": [],
        "entities": [],
        "confidence": 70,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Structured Data Agent  (structured_data domain)
# ─────────────────────────────────────────────────────────────────────────────

_STRUCTURED_SYSTEM = """
You are a FilmDB sub-intent classifier for the STRUCTURED DATA domain.
Return STRICT JSON only. No markdown, no explanation.

IMPORTANT: Actively detect compound/multi-part questions. You may use orthogonal intents from ANY domain in `primary_intent` or `secondary_intents` if needed (e.g., `FILM_ANALYSIS` for critical questions). For example, if asked "Is it a good movie and where can I stream it?", confidently use `FILM_ANALYSIS` as primary and `STREAMING_AVAILABILITY` as secondary.

Valid intents for this domain:
  ENTITY_LOOKUP         – movie/show details, cast, rating, year, poster
  PERSON_LOOKUP         – actor/director biography, people info
  STREAMING_AVAILABILITY – where to watch, available on which platform
  AWARD_LOOKUP          – Oscar, Academy Awards, BAFTA, etc.
  TRENDING              – trending/popular/current movies
  TOP_RATED             – top-rated movies (genre/year filter)
  FILMOGRAPHY           – director or actor list of works
  DOWNLOAD              – public domain download request
  SIMILARITY            – movies similar to a given movie (e.g., "movies like Inception")
  GENRE_TOP             – best or top-rated movies in a genre (e.g., "best sci-fi movies")
  UNDERRATED            – hidden gems, underrated movies, overlooked masterpieces

Schema: {"primary_intent":"...","secondary_intents":[],"entities":[],"confidence":90}
Entity format: [{"type":"movie"|"person"|"genre"|"year"|"platform","value":"..."}]

Examples:
- "tell me about Inception" → {"primary_intent":"ENTITY_LOOKUP","secondary_intents":[],"entities":[{"type":"movie","value":"Inception"}],"confidence":95}
- "who is Kubrick" → {"primary_intent":"PERSON_LOOKUP","secondary_intents":[],"entities":[{"type":"person","value":"Stanley Kubrick"}],"confidence":95}
- "where can I stream The Batman" → {"primary_intent":"STREAMING_AVAILABILITY","secondary_intents":[],"entities":[{"type":"movie","value":"The Batman"}],"confidence":95}
- "oscar nominations 2026" → {"primary_intent":"OSCAR_LOOKUP","secondary_intents":["GENERAL_AWARD_LOOKUP"],"entities":[{"type":"year","value":"2026"}],"confidence":95}
- "kubrick filmography" → {"primary_intent":"FILMOGRAPHY","secondary_intents":["PERSON_LOOKUP"],"entities":[{"type":"person","value":"Stanley Kubrick"}],"confidence":95}
- "best movies by Kamal" → {"primary_intent":"FILMOGRAPHY","secondary_intents":["TOP_RATED"],"entities":[{"type":"person","value":"Kamal Haasan"}],"confidence":95}
- "explain 2001 space odyssey" → {"primary_intent":"ENTITY_LOOKUP","secondary_intents":[],"entities":[{"type":"movie","value":"2001: A Space Odyssey"}],"confidence":95}
- "is the godfather a good movie and where can i stream it" → {"primary_intent":"FILM_ANALYSIS","secondary_intents":["STREAMING_AVAILABILITY"],"entities":[{"type":"movie","value":"The Godfather"}],"confidence":90}
"""

class StructuredDataAgent:
    def classify(self, message: str, llm) -> dict:
        user = f"User message: {message}\nReturn JSON only."
        result = _parse_json(llm.intent_classify(_STRUCTURED_SYSTEM, user),
                             _base_default("ENTITY_LOOKUP"))
        result.setdefault("domain", "structured_data")
        return result


# ─────────────────────────────────────────────────────────────────────────────
# 2. Film Criticism Agent  (film_criticism domain)
# ─────────────────────────────────────────────────────────────────────────────

_CRITICISM_SYSTEM = """
You are a FilmDB sub-intent classifier for the FILM CRITICISM domain.
Return STRICT JSON only.

IMPORTANT: Actively detect compound/multi-part questions. If the user asks for orthogonal tasks (e.g., critical analysis AND streaming availability), confidently populate the `secondary_intents` array with the orthogonal intent from any domain (e.g., `["STREAMING_AVAILABILITY"]`).

Valid intents:
  FILM_ANALYSIS         – why is director X great, critical reception, appreciation, stylistic analysis
  DIRECTOR_COMPARISON   – comparing two directors (style, career, vision)
  FILM_COMPARISON       – comparing two films critically (not just facts)
  CONCEPTUAL_EXPLANATION – explain a critic's perspective or specific critical lens

Cross-domain intents (use in secondary_intents when the user also asks for these):
  ENTITY_LOOKUP           – movie/show details, cast, rating, year
  PERSON_LOOKUP           – actor/director biography, people info
  RECOMMENDATION          – movies similar to X, suggest films, similar movies
  STREAMING_AVAILABILITY  – where to watch, available on which platform
  DOWNLOAD                – public domain download request

Schema: {"primary_intent":"...","secondary_intents":[],"entities":[],"confidence":90}
Entity format: [{"type":"movie"|"person","value":"..."}]

Examples:
- "what do critics say about 2001" → {"primary_intent":"CRITIC_REVIEW","secondary_intents":[],"entities":[{"type":"movie","value":"2001: A Space Odyssey"}],"confidence":90}
- "why is Lynch a great director" → {"primary_intent":"DIRECTOR_ANALYSIS","secondary_intents":[],"entities":[{"type":"person","value":"David Lynch"}],"confidence":90}
- "compare Kubrick and Nolan as directors" → {"primary_intent":"DIRECTOR_COMPARISON","secondary_intents":[],"entities":[{"type":"person","value":"Stanley Kubrick"},{"type":"person","value":"Christopher Nolan"}],"confidence":90}
- "compare Parasite and Snowpiercer critically" → {"primary_intent":"FILM_COMPARISON","secondary_intents":[],"entities":[{"type":"movie","value":"Parasite"},{"type":"movie","value":"Snowpiercer"}],"confidence":88}
- "is The Godfather a good movie and where can I stream it" → {"primary_intent":"FILM_ANALYSIS","secondary_intents":["STREAMING_AVAILABILITY"],"entities":[{"type":"movie","value":"The Godfather"}],"confidence":90}
"""

class FilmCriticismAgent:
    def classify(self, message: str, llm) -> dict:
        user = f"User message: {message}\nReturn JSON only."
        result = _parse_json(llm.intent_classify(_CRITICISM_SYSTEM, user),
                             _base_default("CRITIC_REVIEW"))
        result.setdefault("domain", "film_criticism")
        return result


# ─────────────────────────────────────────────────────────────────────────────
# 3. Film Theory Agent  (film_theory domain)
# ─────────────────────────────────────────────────────────────────────────────

_THEORY_SYSTEM = """
You are a FilmDB sub-intent classifier for the FILM THEORY domain.
Return STRICT JSON only.

IMPORTANT: Actively detect compound/multi-part questions and confidently populate the `secondary_intents` array if the user asks for multiple orthogonal topics.

Valid intents:
  CONCEPTUAL_EXPLANATION  – define/explain a film theory concept (auteur theory, male gaze, etc.)
  THEORETICAL_ANALYSIS    – apply theory to a film or director
  COMPARATIVE_THEORY      – compare two theoretical frameworks

Cross-domain intents (use in secondary_intents when the user also asks for these):
  ENTITY_LOOKUP           – movie/show details, cast, rating, year
  PERSON_LOOKUP           – actor/director biography, people info
  RECOMMENDATION          – movies similar to X, suggest films, similar movies
  STREAMING_AVAILABILITY  – where to watch, available on which platform
  DOWNLOAD                – public domain download request

Schema: {"primary_intent":"...","secondary_intents":[],"entities":[],"confidence":90}

Examples:
- "what is auteur theory" → {"primary_intent":"CONCEPTUAL_EXPLANATION","secondary_intents":[],"entities":[],"confidence":90}
- "explain the male gaze in Hitchcock films" → {"primary_intent":"THEORETICAL_ANALYSIS","secondary_intents":[],"entities":[{"type":"person","value":"Alfred Hitchcock"}],"confidence":88}
- "how does montage theory differ from deep focus" → {"primary_intent":"COMPARATIVE_THEORY","secondary_intents":[],"entities":[],"confidence":85}
- "what is auteur theory and suggest some auteur films to watch" → {"primary_intent":"CONCEPTUAL_EXPLANATION","secondary_intents":["RECOMMENDATION"],"entities":[],"confidence":88}
"""

class FilmTheoryAgent:
    def classify(self, message: str, llm) -> dict:
        user = f"User message: {message}\nReturn JSON only."
        result = _parse_json(llm.intent_classify(_THEORY_SYSTEM, user),
                             _base_default("CONCEPTUAL_EXPLANATION"))
        result.setdefault("domain", "film_theory")
        return result


# ─────────────────────────────────────────────────────────────────────────────
# 4. Film History Agent  (film_history domain)
# ─────────────────────────────────────────────────────────────────────────────

_HISTORY_SYSTEM = """
You are a FilmDB sub-intent classifier for the FILM HISTORY domain.
Return STRICT JSON only.

IMPORTANT: Actively detect compound/multi-part questions and confidently populate the `secondary_intents` array if the user asks for multiple orthogonal topics.

Valid intents:
  HISTORICAL_CONTEXT   – how/when did something happen in cinema history
  MOVEMENT_OVERVIEW    – about a cinema movement (French New Wave, neorealism, etc.)
  BIOGRAPHY            – director/filmmaker/actor life story and career

Cross-domain intents (use in secondary_intents when the user also asks for these):
  ENTITY_LOOKUP           – movie details, cast, rating, year
  PERSON_LOOKUP           – actor/director biography, people info
  RECOMMENDATION          – movies similar to X, suggest films, suggest movies from an era, similar movies
  STREAMING_AVAILABILITY  – where to watch, available on which platform
  DOWNLOAD                – public domain download request
  TOP_RATED               – top-rated or best movies from an era or movement

Schema: {"primary_intent":"...","secondary_intents":[],"entities":[],"confidence":90}

Examples:
- "how did sound change cinema" → {"primary_intent":"HISTORICAL_CONTEXT","secondary_intents":[],"entities":[],"confidence":88}
- "tell me about Italian Neorealism" → {"primary_intent":"MOVEMENT_OVERVIEW","secondary_intents":[],"entities":[],"confidence":92}
- "Tarkovsky biography" → {"primary_intent":"BIOGRAPHY","secondary_intents":[],"entities":[{"type":"person","value":"Andrei Tarkovsky"}],"confidence":90}
- "what is Italian Neorealism and suggest some movies to watch" → {"primary_intent":"MOVEMENT_OVERVIEW","secondary_intents":["RECOMMENDATION"],"entities":[],"confidence":90}
- "tell me about German Expressionism and show me top rated movies from that era" → {"primary_intent":"MOVEMENT_OVERVIEW","secondary_intents":["TOP_RATED"],"entities":[],"confidence":90}
"""

class FilmHistoryAgent:
    def classify(self, message: str, llm) -> dict:
        user = f"User message: {message}\nReturn JSON only."
        result = _parse_json(llm.intent_classify(_HISTORY_SYSTEM, user),
                             _base_default("HISTORICAL_CONTEXT"))
        result.setdefault("domain", "film_history")
        return result


# ─────────────────────────────────────────────────────────────────────────────
# 5. Film Aesthetics Agent  (film_aesthetics domain)
# ─────────────────────────────────────────────────────────────────────────────

_AESTHETICS_SYSTEM = """
You are a FilmDB sub-intent classifier for the FILM AESTHETICS domain.
Return STRICT JSON only.

IMPORTANT: Actively detect compound/multi-part questions and confidently populate the `secondary_intents` array if the user asks for multiple orthogonal topics.

Valid intents:
  VISUAL_ANALYSIS      – cinematography, visual style, shot analysis for a film/director
  TECHNIQUE_EXPLANATION – explain a technique (long take, deep focus, rack focus, etc.)
  STYLE_COMPARISON     – compare visual styles of two directors

Cross-domain intents (use in secondary_intents when the user also asks for these):
  ENTITY_LOOKUP           – movie details, cast, rating, year
  PERSON_LOOKUP           – actor/director biography, people info
  RECOMMENDATION          – movies similar to X, suggest films, similar movies
  STREAMING_AVAILABILITY  – where to watch, available on which platform
  DOWNLOAD                – public domain download request

Schema: {"primary_intent":"...","secondary_intents":[],"entities":[],"confidence":90}

Examples:
- "explain Kubrick's use of one-point perspective" → {"primary_intent":"VISUAL_ANALYSIS","secondary_intents":[],"entities":[{"type":"person","value":"Stanley Kubrick"}],"confidence":90}
- "what is a long take" → {"primary_intent":"TECHNIQUE_EXPLANATION","secondary_intents":[],"entities":[],"confidence":92}
- "compare Tarkovsky and Antonioni's visual styles" → {"primary_intent":"STYLE_COMPARISON","secondary_intents":[],"entities":[{"type":"person","value":"Andrei Tarkovsky"},{"type":"person","value":"Michelangelo Antonioni"}],"confidence":88}
- "what makes French New Wave films aesthetically distinct and suggest some to watch" → {"primary_intent":"VISUAL_ANALYSIS","secondary_intents":["RECOMMENDATION"],"entities":[],"confidence":88}
"""

class FilmAestheticsAgent:
    def classify(self, message: str, llm) -> dict:
        user = f"User message: {message}\nReturn JSON only."
        result = _parse_json(llm.intent_classify(_AESTHETICS_SYSTEM, user),
                             _base_default("VISUAL_ANALYSIS"))
        result.setdefault("domain", "film_aesthetics")
        return result


# ─────────────────────────────────────────────────────────────────────────────
# 6. Film Production Agent  (film_production domain)
# ─────────────────────────────────────────────────────────────────────────────

_PRODUCTION_SYSTEM = """
You are a FilmDB sub-intent classifier for the FILM PRODUCTION domain.
Return STRICT JSON only.

IMPORTANT: Actively detect compound/multi-part questions and confidently populate the `secondary_intents` array if the user asks for multiple orthogonal topics.

Valid intents:
  PRODUCTION_GUIDANCE    – how to make a film, production process
  SCREENWRITING_HELP     – screenplay structure, story beats, dialogue, adaptation, specific craft tutorial (how to write a scene, character arc)
  TECHNIQUE_TUTORIAL     – How to direct a movie, how to edit a movie, how to shoot a movie, how to produce a movie, how to write a movie, how to direct a movie, how to edit a movie, how to shoot a movie, how to produce a movie, how to write a movie
  ACTING_GUIDANCE        – How to act in a movie, how to be an actor, how to be a good actor, how to be a great actor, how to be a method actor, how to be a method actor, how to be a method actor, how to be a method actor, how to be a method actor, how to be a method actor

Schema: {"primary_intent":"...","secondary_intents":[],"entities":[],"confidence":90}

Examples:
- "how do I write a three-act screenplay" → {"primary_intent":"SCREENWRITING_HELP","secondary_intents":[],"entities":[],"confidence":90}
- "how is a documentary made" → {"primary_intent":"PRODUCTION_GUIDANCE","secondary_intents":[],"entities":[],"confidence":88}
- "how to write a character arc" → {"primary_intent":"TECHNIQUE_TUTORIAL","secondary_intents":[],"entities":[],"confidence":88}
- "how to write a screenplay and suggest some well-written films" → {"primary_intent":"SCREENWRITING_HELP","secondary_intents":["RECOMMENDATION"],"entities":[],"confidence":88}
- "how to act in a movie and suggest some good movies to watch" → {"primary_intent":"ACTING_GUIDANCE","secondary_intents":["RECOMMENDATION"],"entities":[],"confidence":88}
- The Query may contain some books like screenplay foundation by Syd Field, Save the cat by Blake Snyder, Story by Robert McKee, etc... these books give techniques and practices for writing a screenplay, like wise for directing, acting, cinemotography there are many books so choose appropriately
"""

class FilmProductionAgent:
    def classify(self, message: str, llm) -> dict:
        user = f"User message: {message}\nReturn JSON only."
        result = _parse_json(llm.intent_classify(_PRODUCTION_SYSTEM, user),
                             _base_default("PRODUCTION_GUIDANCE"))
        result.setdefault("domain", "film_production")
        return result


# ─────────────────────────────────────────────────────────────────────────────
# 7. General Agent  (greetings / meta)
# ─────────────────────────────────────────────────────────────────────────────

class GeneralAgent:
    """No LLM needed — deterministic for greetings / meta queries."""
    def classify(self, message: str, llm=None) -> dict:
        return {
            "primary_intent": "BOT_INTERACTION",
            "secondary_intents": [],
            "entities": [],
            "confidence": 100,
            "domain": "general",
        }


# 7. Live Search Agent  (live_search domain)
# ─────────────────────────────────────────────────────────────────────────────

_LIVE_SEARCH_SYSTEM = """
You are a FilmDB sub-intent classifier for the LIVE SEARCH domain.
Return STRICT JSON only.

Valid intents:
  LATEST_NEWS           – latest news, breaking news, recent developments, current status
  TRENDING              – what's popular now, trending films/people
  UPCOMING              – movie releases in the near future, dune 3 release, etc.
  BOX_OFFICE            – commercial performance, collections, profits
  CRITIC_REVIEW         – recent critical consensus from web sources

Supporting entities:
  - movie               – name of the film
  - person              – name of actor/director
  - region              – "Tamil", "Indian", "Global/Hollywood" (detected from context)
  - category            – "Awards", "Industry", "Critics"

Schema: {"primary_intent":"...","secondary_intents":[],"entities":[],"confidence":90}
Entity format: [{"type":"movie"|"person"|"genre"|"region"|"category","value":"..."}]

Examples:
- "latest news about Nolan" → {"primary_intent":"LATEST_NEWS","secondary_intents":[],"entities":[{"type":"person","value":"Christopher Nolan"},{"type":"region","value":"Global"}],"confidence":98}
- "Dune 3 release date" → {"primary_intent":"UPCOMING","secondary_intents":[],"entities":[{"type":"movie","value":"Dune 3"},{"type":"region","value":"Global"}],"confidence":98}
- "is Joker 2 a flop or hit" → {"primary_intent":"BOX_OFFICE","secondary_intents":["CRITIC_REVIEW"],"entities":[{"type":"movie","value":"Joker 2"},{"type":"category","value":"Industry"}],"confidence":95}
- "Ajith health updates" → {"primary_intent":"LATEST_NEWS","secondary_intents":[],"entities":[{"type":"person","value":"Ajith Kumar"},{"type":"region","value":"Tamil"}],"confidence":98}
- "Oscar 2026 winners" → {"primary_intent":"AWARD_LOOKUP","secondary_intents":[],"entities":[{"type":"category","value":"Awards"}],"confidence":98}
"""

class LiveSearchAgent:
    def classify(self, message: str, llm) -> dict:
        user = f"User message: {message}\nReturn JSON only."
        result = _parse_json(llm.intent_classify(_LIVE_SEARCH_SYSTEM, user),
                             _base_default("LATEST_NEWS"))
        result.setdefault("domain", "live_search")
        return result


# ─────────────────────────────────────────────────────────────────────────────
# Registry
# ─────────────────────────────────────────────────────────────────────────────

DOMAIN_AGENTS: dict[str, object] = {
    "structured_data": StructuredDataAgent(),
    "film_criticism":  FilmCriticismAgent(),
    "film_theory":     FilmTheoryAgent(),
    "film_history":    FilmHistoryAgent(),
    "film_aesthetics": FilmAestheticsAgent(),
    "film_production": FilmProductionAgent(),
    "live_search":     LiveSearchAgent(),
    "general":         GeneralAgent(),
}

