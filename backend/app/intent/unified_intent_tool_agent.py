"""
UnifiedIntentToolAgent
======================
Tier-2 of the Adaptive Hybrid Agent Architecture.

Replaces: HybridIntentClassifier (Tier-2 LLM pass) + tool_selector.py
Keeps:    DomainClassifier (Tier-1), Governance, EntityResolver, execution pipeline

Single LLM call that simultaneously:
  1. Classifies primary intent
  2. Extracts entities
  3. Selects tools (with tool descriptions — self-healing, no manual maps)
  4. Enforces temporal rules as a deterministic post-LLM safety layer

Multi-domain: one prompt, one call, both domains handled natively.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.intent.domain_classifier import DomainResult
from app.intent.temporal_context import TemporalContextBuilder

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Shared tool description block (injected into every prompt)
# ─────────────────────────────────────────────────────────────────────────────
_TOOL_DESCRIPTIONS = """
AVAILABLE TOOLS (select only what you need):

  tmdb              – Movie/person metadata: TRAILERS/VIDEOS, cast, director, year, rating, genres, runtime
  watchmode         – Streaming availability and platform info (Netflix, Prime, etc.)
  oscar_award       – Academy Award nominations and wins (historically up to cutoff)
  imdb_awards       – Broader award history including BAFTA, Golden Globe, etc.
  cinema_search     – Live web search for current/recent cinema news and events, recently released movies, fresh critic essays, youtube reviews, etc. [USE for post-cutoff queries]
  recommendation_engine – Similar movie recommendations based on query
  wikipedia         – Encyclopedia articles for background and synthesis
  rag               – Internal knowledge base (books, essays, film analyses)
                      Specify domains=[...] to target specific collections.
                      Valid domains: film_theory, film_criticism, film_history,
                        film_aesthetics, film_production, scripts,
                        film_analysis, film_studies

Tool selection rules:
  - SELECT MINIMUM tools needed to answer the query accurately
  - For post-cutoff or "current/latest/2025+" queries: ALWAYS include cinema_search
  - For streaming questions: include watchmode (NOT tmdb)
  - For award queries: include oscar_award; add cinema_search if year > 2024
  - For analysis/theory/history: include rag with appropriate domains
  - For factual lookups (cast, year, director) OR fetching trailers/youtube videos: ALWAYS include tmdb
  - Maximum 4 tools per query
"""

# ─────────────────────────────────────────────────────────────────────────────
# Domain-specific system prompts
# ─────────────────────────────────────────────────────────────────────────────

_STRUCTURED_SYSTEM = """You are a FilmDB intent and tool classifier for STRUCTURED DATA queries.
Return STRICT JSON only. No markdown.

Your domain covers: factual movie/person lookups, streaming availability, awards,
filmographies, recommendations, plot summaries, trending/top-rated lists.

Valid intents:
  ENTITY_LOOKUP, PERSON_LOOKUP, STREAMING_AVAILABILITY, AWARD_LOOKUP,
  TRENDING, TOP_RATED, FILMOGRAPHY, DOWNLOAD, SIMILARITY, GENRE_TOP, UNDERRATED,
  FILM_ANALYSIS, COMPARISON, LATEST_NEWS

Schema:
{
  "primary_intent": "...",
  "secondary_intents": [],
  "entities": [{"type": "movie|person|genre|year|platform|region", "value": "..."}],
  "tools": [{"name": "...", "arguments": {...}}],
  "metadata_filters": {"director": null, "title": null, "entity_name": null},
  "expanded_query": "rewrite the user query including entity names, related film titles, and descriptive keywords to maximise search recall",
  "knowledge_source_strategy": "internal_only|verify_with_tools|external_required",
  "temporal_note": "...",
  "confidence": 90
}

metadata_filters rules:
  - Set "director" if the query mentions a specific director by name
  - Set "title" if the query mentions a specific movie/show by name
  - Set "entity_name" if querying about a specific person or film for essay collections
  - Leave fields as null if not applicable — do NOT guess
  - For abstract/conceptual queries with no specific entity, leave all null

expanded_query rules:
  - Always include the original query terms
  - Add the full names of any mentioned entities (director, actor, film)
  - Add 3-5 related keywords or synonyms that would appear in relevant documents
  - For movie queries: add director name, year, genre
  - For person queries: add their notable films
  - Keep under 50 words
"""

_FILM_THEORY_SYSTEM = """You are a FilmDB intent and tool classifier for FILM THEORY queries.
Return STRICT JSON only. No markdown.

Your domain covers: theoretical frameworks, semiotics, apparatus theory, spectatorship,
feminist film theory, montage theory, realism vs formalism, phenomenology, Bazin, Eisenstein,
Metz, Mulvey, Deleuze, Lacan, ontology of cinema, narrative theory.

Valid intents:
  THEORETICAL_ANALYSIS, CONCEPTUAL_EXPLANATION, MOVEMENT_OVERVIEW,
  HISTORICAL_CONTEXT, STYLE_COMPARISON, FILM_ANALYSIS, DIRECTOR_ANALYSIS

Schema:
{
  "primary_intent": "...",
  "secondary_intents": [],
  "entities": [{"type": "concept|theorist|movement|film|person", "value": "..."}],
  "tools": [{"name": "...", "arguments": {...}}],
  "metadata_filters": {"director": null, "title": null, "entity_name": null},
  "expanded_query": "rewrite query with theorist names, related concepts, academic synonyms, and key terms from film theory literature",
  "knowledge_source_strategy": "internal_only|verify_with_tools|external_required",
  "temporal_note": "...",
  "confidence": 90
}

metadata_filters: Leave all null for pure theory queries. Set entity_name only if a specific theorist or filmmaker is the focus.
expanded_query: ALWAYS enrich with academic synonyms (e.g. "male gaze" → add "Laura Mulvey spectatorship voyeurism scopophilia visual pleasure").
"""

_FILM_CRITICISM_SYSTEM = """You are a FilmDB intent and tool classifier for FILM CRITICISM queries.
Return STRICT JSON only. No markdown.

Your domain covers: critical evaluation, auteur studies, thematic reading,
cultural significance, interpretive essays, retrospective criticism, filmmaker writings.

Valid intents:
  FILM_ANALYSIS, DIRECTOR_ANALYSIS, STYLE_COMPARISON, CONCEPTUAL_EXPLANATION,
  MOVEMENT_OVERVIEW, CRITIC_REVIEW, COMPARISON

Schema:
{
  "primary_intent": "...",
  "secondary_intents": [],
  "entities": [{"type": "film|person|movement|concept", "value": "..."}],
  "tools": [{"name": "...", "arguments": {...}}],
  "metadata_filters": {"director": null, "title": null, "entity_name": null},
  "expanded_query": "rewrite query with filmmaker names, film titles, critical terms, and thematic keywords",
  "knowledge_source_strategy": "internal_only|verify_with_tools|external_required",
  "temporal_note": "...",
  "confidence": 90
}

metadata_filters: Set director/title if a specific film or filmmaker is the focus. Leave null for broad critical discussions.
expanded_query: Include the filmmaker's notable works and critical vocabulary.
"""

_FILM_HISTORY_SYSTEM = """You are a FilmDB intent and tool classifier for FILM HISTORY queries.
Return STRICT JSON only. No markdown.

Your domain covers: cinema movements, eras, historical developments, biographies,
silent cinema, expressionism, neorealism, New Wave, New Hollywood, national cinemas.

Valid intents:
  HISTORICAL_CONTEXT, MOVEMENT_OVERVIEW, CONCEPTUAL_EXPLANATION,
  DIRECTOR_ANALYSIS, FILM_ANALYSIS

Schema:
{
  "primary_intent": "...",
  "secondary_intents": [],
  "entities": [{"type": "movement|era|person|film|country", "value": "..."}],
  "tools": [{"name": "...", "arguments": {...}}],
  "metadata_filters": {"director": null, "title": null, "entity_name": null},
  "expanded_query": "rewrite query with era dates, key directors of the movement, landmark films, and country names",
  "knowledge_source_strategy": "internal_only|verify_with_tools|external_required",
  "temporal_note": "...",
  "confidence": 90
}

metadata_filters: Set entity_name for specific filmmaker biographies. Leave null for movement/era queries.
expanded_query: Include key directors, dates, and landmark films of the era/movement.
"""

_FILM_AESTHETICS_SYSTEM = """You are a FilmDB intent and tool classifier for FILM AESTHETICS queries.
Return STRICT JSON only. No markdown.

Your domain covers: visual style, cinematography, mise-en-scène, shot composition,
lighting, color, editing, sound design, camera movement, technical craft.

Valid intents:
  VISUAL_ANALYSIS, STYLE_COMPARISON, FILM_ANALYSIS, DIRECTOR_ANALYSIS,
  CONCEPTUAL_EXPLANATION, HISTORICAL_CONTEXT

Schema:
{
  "primary_intent": "...",
  "secondary_intents": [],
  "entities": [{"type": "film|person|technique|concept", "value": "..."}],
  "tools": [{"name": "...", "arguments": {...}}],
  "metadata_filters": {"director": null, "title": null, "entity_name": null},
  "expanded_query": "rewrite query with technique names, cinematographer names, visual terminology, and example films",
  "knowledge_source_strategy": "internal_only|verify_with_tools|external_required",
  "temporal_note": "...",
  "confidence": 90
}

metadata_filters: Set director if visual style of a specific filmmaker is discussed. Leave null for general technique queries.
expanded_query: Include technical terminology (e.g. "long take" → add "sequence shot plan-séquence continuous take").
"""

_FILM_ANALYSIS_SYSTEM = """You are a FilmDB intent and tool classifier for FILM ANALYSIS queries.
Return STRICT JSON only. No markdown.

Your domain covers: close readings of specific films, auteur studies,
director-specific analysis, scene-by-scene breakdowns, comparative director studies,
thematic/symbolic readings anchored to specific works.

Valid intents:
  FILM_ANALYSIS, DIRECTOR_ANALYSIS, VISUAL_ANALYSIS, STYLE_COMPARISON,
  COMPARISON, CONCEPTUAL_EXPLANATION

Schema:
{
  "primary_intent": "...",
  "secondary_intents": [],
  "entities": [{"type": "film|person|technique|scene|theme", "value": "..."}],
  "tools": [{"name": "...", "arguments": {...}}],
  "metadata_filters": {"director": null, "title": null, "entity_name": null},
  "expanded_query": "rewrite query with director name, film title, character names, thematic terms, and related analytical vocabulary",
  "knowledge_source_strategy": "internal_only|verify_with_tools|external_required",
  "temporal_note": "...",
  "confidence": 90
}

metadata_filters: Set director and/or title when analysing a specific film or filmmaker. Set entity_name to the filmmaker for essay lookups.
expanded_query: Include character names, scene descriptions, and thematic keywords.
"""

_FILM_STUDIES_SYSTEM = """You are a FilmDB intent and tool classifier for FILM STUDIES queries.
Return STRICT JSON only. No markdown.

Your domain covers: academic film studies, national cinema surveys, cultural studies,
gender/identity in cinema, postcolonial cinema, Tamil/Indian cinema as cultural system,
sociology of cinema, film education, multi-perspective institutional studies.

Valid intents:
  CONCEPTUAL_EXPLANATION, HISTORICAL_CONTEXT, MOVEMENT_OVERVIEW,
  FILM_ANALYSIS, DIRECTOR_ANALYSIS

Schema:
{
  "primary_intent": "...",
  "secondary_intents": [],
  "entities": [{"type": "concept|country|movement|film|person", "value": "..."}],
  "tools": [{"name": "...", "arguments": {...}}],
  "metadata_filters": {"director": null, "title": null, "entity_name": null},
  "expanded_query": "rewrite query with country names, cultural terms, key scholars, and related academic concepts",
  "knowledge_source_strategy": "internal_only|verify_with_tools|external_required",
  "temporal_note": "...",
  "confidence": 90
}

metadata_filters: Leave null for broad academic queries. Set entity_name for country-specific or person-specific studies.
expanded_query: Include country names, academic terminology, key scholars, and related films.
"""

_FILM_PRODUCTION_SYSTEM = """You are a FilmDB intent and tool classifier for FILM PRODUCTION queries.
Return STRICT JSON only. No markdown.

Your domain covers: practical filmmaking craft — directing, screenwriting, editing,
cinematography practice, pre/post-production, script development, budgeting, distribution.

Valid intents:
  CONCEPTUAL_EXPLANATION, FILM_ANALYSIS, DIRECTOR_ANALYSIS, VISUAL_ANALYSIS

Schema:
{
  "primary_intent": "...",
  "secondary_intents": [],
  "entities": [{"type": "concept|technique|film|person", "value": "..."}],
  "tools": [{"name": "...", "arguments": {...}}],
  "metadata_filters": {"director": null, "title": null, "entity_name": null},
  "expanded_query": "rewrite query with craft terminology, relevant book titles, technique names, and example films",
  "knowledge_source_strategy": "internal_only|verify_with_tools|external_required",
  "temporal_note": "...",
  "confidence": 90
}

metadata_filters: Leave null for craft/technique queries. Set director only if discussing a specific filmmaker's production methods.
expanded_query: Include book titles (Screenplay by Syd Field, Save the Cat, Story by McKee) and technique names.
"""

_GENERAL_SYSTEM = """You are a FilmDB intent and tool classifier.
Return STRICT JSON only. No markdown.

Schema:
{
  "primary_intent": "BOT_INTERACTION",
  "secondary_intents": [],
  "entities": [],
  "tools": [],
  "knowledge_source_strategy": "internal_only",
  "temporal_note": "",
  "confidence": 99
}
"""

# Domain → system prompt
DOMAIN_SYSTEMS: dict[str, str] = {
    "structured_data":  _STRUCTURED_SYSTEM,
    "film_theory":      _FILM_THEORY_SYSTEM,
    "film_criticism":   _FILM_CRITICISM_SYSTEM,
    "film_history":     _FILM_HISTORY_SYSTEM,
    "film_aesthetics":  _FILM_AESTHETICS_SYSTEM,
    "film_analysis":    _FILM_ANALYSIS_SYSTEM,
    "film_studies":     _FILM_STUDIES_SYSTEM,
    "film_production":  _FILM_PRODUCTION_SYSTEM,
    "general":          _GENERAL_SYSTEM,
}

# ─────────────────────────────────────────────────────────────────────────────
# Multi-domain prompt builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_multi_domain_system(
    primary_domain: str,
    secondary_domain: str,
    primary_score: float,
    secondary_score: float,
) -> str:
    """One prompt that handles both domains in a single LLM call."""
    p_desc = DOMAIN_SYSTEMS.get(primary_domain, _STRUCTURED_SYSTEM)
    s_desc = DOMAIN_SYSTEMS.get(secondary_domain, _STRUCTURED_SYSTEM)

    return f"""You are a FilmDB intent and tool classifier analyzing a MULTI-DOMAIN query.
Return STRICT JSON only. No markdown.

PRIMARY DOMAIN   : {primary_domain}   (confidence {primary_score:.0%})
Secondary domain : {secondary_domain} (confidence {secondary_score:.0%})

DOMAIN GUIDANCE:
Primary   → {p_desc.split(chr(10))[3].strip() if len(p_desc.split(chr(10))) > 3 else ""}
Secondary → {s_desc.split(chr(10))[3].strip() if len(s_desc.split(chr(10))) > 3 else ""}

TASK:
1. Anchor primary_intent to the higher-confidence domain
2. Pull secondary_intents from the lower-confidence domain if relevant
3. Select tools from BOTH domains — use rag with domains=[...] to span both
4. Maximum 4 tools total

Schema:
{{
  "primary_intent": "...",
  "secondary_intents": [],
  "entities": [{{"type": "...", "value": "..."}}],
  "tools": [{{"name": "...", "arguments": {{...}}}}],
  "metadata_filters": {{"director": null, "title": null, "entity_name": null}},
  "expanded_query": "rewrite query with entity names, synonyms, and domain-specific keywords",
  "domain": "{primary_domain}",
  "secondary_domain": "{secondary_domain}",
  "knowledge_source_strategy": "internal_only|verify_with_tools|external_required",
  "temporal_note": "...",
  "confidence": 90
}}
"""


# ─────────────────────────────────────────────────────────────────────────────
# Default fallback tools per domain (used when LLM fails)
# ─────────────────────────────────────────────────────────────────────────────

_FALLBACK_TOOLS: dict[str, list[dict]] = {
    "structured_data":  [{"name": "tmdb",        "arguments": {}}],
    "film_theory":      [{"name": "rag",          "arguments": {"domains": ["film_theory"]}}],
    "film_criticism":   [{"name": "rag",          "arguments": {"domains": ["film_criticism", "film_analysis"]}}],
    "film_history":     [{"name": "rag",          "arguments": {"domains": ["film_history"]}}],
    "film_aesthetics":  [{"name": "rag",          "arguments": {"domains": ["film_aesthetics"]}}],
    "film_analysis":    [{"name": "rag",          "arguments": {"domains": ["film_analysis", "film_criticism"]}}],
    "film_studies":     [{"name": "rag",          "arguments": {"domains": ["film_studies", "film_history"]}}],
    "film_production":  [{"name": "rag",          "arguments": {"domains": ["film_production"]}}],
    "general":          [],
}


# ─────────────────────────────────────────────────────────────────────────────
# Main class
# ─────────────────────────────────────────────────────────────────────────────

class UnifiedIntentToolAgent:
    """
    Single LLM call for intent classification + tool selection.
    Replaces the Tier-2 sub-intent agents AND tool_selector.py.
    """

    def classify_and_select(
        self,
        query: str,
        domain_result: DomainResult,
        llm,
    ) -> dict[str, Any]:
        """
        Args:
            query:         The resolved user message (pronouns already substituted)
            domain_result: Output from Tier-1 DomainClassifier
            llm:           GroqClient instance (uses llm.intent_classify)

        Returns:
            {
                primary_intent, secondary_intents, entities, tools,
                domain, secondary_domain (optional),
                knowledge_source_strategy, temporal_note,
                confidence, domain_score, classifier
            }
        """
        temporal_ctx      = TemporalContextBuilder.get_current_date_context()
        temporal_analysis = TemporalContextBuilder.detect_temporal_type(query)

        # ── Build prompt based on single vs multi-domain mode ─────────────
        if domain_result.mode == "multi":
            primary_domain   = domain_result.top2[0][0]
            secondary_domain = domain_result.top2[1][0]
            primary_score    = domain_result.top2[0][1]
            secondary_score  = domain_result.top2[1][1]

            system = (
                _build_multi_domain_system(
                    primary_domain, secondary_domain,
                    primary_score, secondary_score,
                )
                + "\n\n"
                + _TOOL_DESCRIPTIONS
                + "\n\n"
                + temporal_ctx
            )
        else:
            primary_domain   = domain_result.domain
            secondary_domain = None
            system = (
                DOMAIN_SYSTEMS.get(primary_domain, _STRUCTURED_SYSTEM)
                + "\n\n"
                + _TOOL_DESCRIPTIONS
                + "\n\n"
                + temporal_ctx
            )

        user = f"User query: {query}\nReturn JSON only."

        # ── One LLM call ──────────────────────────────────────────────────
        raw = llm.intent_classify(system, user)
        result = self._parse_json(raw, primary_domain)

        # ── Temporal rule enforcement (deterministic safety layer) ─────────
        result = self._enforce_temporal_rules(result, temporal_analysis, query)

        # ── Attach metadata ───────────────────────────────────────────────
        result.setdefault("domain", primary_domain)
        if secondary_domain and "secondary_domain" not in result:
            result["secondary_domain"] = secondary_domain
        result["domain_score"] = round(domain_result.score, 3)
        result["classifier"]   = "unified_agent"

        logger.info(
            "UnifiedIntentToolAgent: intent=%s domain=%s tools=%s conf=%s temporal=%s",
            result.get("primary_intent"),
            result.get("domain"),
            [t.get("name") for t in result.get("tools", [])],
            result.get("confidence"),
            temporal_analysis.get("type"),
        )
        return result

    # ─────────────────────────────────────────────────────────────────────
    #  Internal
    # ─────────────────────────────────────────────────────────────────────

    def _parse_json(self, raw: str | None, domain: str) -> dict[str, Any]:
        """Parse LLM JSON output with regex fallback and safe defaults."""
        default = {
            "primary_intent":           "ENTITY_LOOKUP" if domain == "structured_data" else "CONCEPTUAL_EXPLANATION",
            "secondary_intents":        [],
            "entities":                 [],
            "tools":                    _FALLBACK_TOOLS.get(domain, []),
            "knowledge_source_strategy": "verify_with_tools",
            "temporal_note":            "",
            "confidence":               65,
        }
        if not raw:
            logger.warning("UnifiedIntentToolAgent: empty LLM response — using fallback")
            return default

        try:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            data  = json.loads(match.group(0) if match else raw)
            if not isinstance(data, dict):
                return default

            # Normalise confidence: float 0-1 → int 0-100
            c = data.get("confidence", 80)
            if isinstance(c, float) and 0 < c <= 1.0:
                c = int(c * 100)
            data["confidence"] = int(c) if isinstance(c, (int, float)) else 80

            # Ensure critical keys exist
            data.setdefault("secondary_intents",        [])
            data.setdefault("entities",                 [])
            data.setdefault("tools",                    _FALLBACK_TOOLS.get(domain, []))
            data.setdefault("knowledge_source_strategy", "verify_with_tools")
            data.setdefault("temporal_note",             "")
            return data

        except (json.JSONDecodeError, AttributeError):
            logger.warning("UnifiedIntentToolAgent: JSON parse failed — using fallback. raw=%s", raw[:200])
            return default

    def _enforce_temporal_rules(
        self,
        result: dict[str, Any],
        temporal_analysis: dict[str, Any],
        query: str,
    ) -> dict[str, Any]:
        """
        Deterministic post-LLM safety guard for temporal correctness.
        Ensures post-cutoff queries always have cinema_search in the tool list.
        """
        if not temporal_analysis.get("requires_live_data"):
            return result

        tools = result.get("tools", [])
        tool_names = {t.get("name") for t in tools}

        if "cinema_search" not in tool_names:
            logger.info(
                "TemporalEnforcement: adding cinema_search for post-cutoff query '%s'", query[:60]
            )
            tools.append({
                "name":      "cinema_search",
                "arguments": {"query": query},
            })
            result["tools"] = tools
            result["knowledge_source_strategy"] = "external_required"
            result["temporal_note"] = (
                temporal_analysis.get("note", "")
                + " — cinema_search added by temporal enforcement"
            )

        return result

