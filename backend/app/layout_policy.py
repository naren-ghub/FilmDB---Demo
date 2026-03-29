from typing import Any


def select_response_mode(
    primary_intent: str, secondary_intents: list[str], tool_outputs: dict[str, dict]
) -> str:
    watchmode = tool_outputs.get("watchmode", {})
    # Check both current recommendation_engine and legacy similarity tool
    recom_out = tool_outputs.get("recommendation_engine", tool_outputs.get("similarity", {}))

    has_streaming = (
        watchmode.get("status") == "success"
        and bool(watchmode.get("data", {}).get("platforms"))
    )
    has_recs = (
        recom_out.get("status") == "success"
        and bool(recom_out.get("data", {}).get("recommendations"))
    )
    has_awards = (
        tool_outputs.get("oscar_award", {}).get("status") == "success"
        or tool_outputs.get("imdb_awards", {}).get("status") == "success"
    )

    # Priority 1: Disambiguation / Clarification
    for out in tool_outputs.values():
        if out.get("status") == "disambiguation":
            return "CLARIFICATION"

    # Primary intent routing
    if primary_intent == "STREAMING_AVAILABILITY":
        return "AVAILABILITY_FOCUS"
    if primary_intent in ("RECOMMENDATION", "TRENDING", "UPCOMING", "TOP_RATED"):
        return "RECOMMENDATION_GRID"
    if primary_intent == "ENTITY_LOOKUP":
        return "FULL_CARD" if (tool_outputs.get("imdb") or tool_outputs.get("tmdb")) else "MINIMAL_CARD"
    if primary_intent == "DOWNLOAD":
        return "MINIMAL_CARD"
    if primary_intent == "ILLEGAL_DOWNLOAD_REQUEST":
        return "EXPLANATION_ONLY"
    if primary_intent == "PERSON_LOOKUP":
        # Upgrade to FILMOGRAPHY_LIST if secondary intent signals filmography
        if "FILMOGRAPHY" in secondary_intents:
            return "FILMOGRAPHY_LIST"
        return "EXPLANATION_ONLY"
    if primary_intent == "FILMOGRAPHY":
        return "FILMOGRAPHY_LIST"
    if primary_intent == "PLOT_EXPLANATION":
        return "ANALYSIS_TEXT"
    if primary_intent in (
        "FILM_ANALYSIS", "VISUAL_ANALYSIS", "DIRECTOR_ANALYSIS",
        "CONCEPTUAL_EXPLANATION", "THEORETICAL_ANALYSIS",
        "MOVEMENT_OVERVIEW", "HISTORICAL_CONTEXT", "STYLE_COMPARISON",
        "FILM_COMPARISON", "CRITIC_REVIEW",
    ):
        return "ANALYSIS_TEXT"
    if primary_intent == "COMPARISON":
        return "COMPARISON_TABLE"
    if primary_intent == "AWARD_LOOKUP":
        return "AWARDS_CARD" if has_awards else "EXPLANATION_ONLY"
    if primary_intent in ("GREETING", "GENERAL_CONVERSATION", "BOT_INTERACTION"):
        return "EXPLANATION_ONLY"

    # Secondary intent fallbacks
    if "STREAMING_AVAILABILITY" in secondary_intents and has_streaming:
        return "EXPLANATION_PLUS_AVAILABILITY"
    if "RECOMMENDATION" in secondary_intents and has_recs:
        return "RECOMMENDATION_GRID"

    return "EXPLANATION_ONLY"


SEGMENT_MOVIE_CARD   = "MOVIE_CARD"       # replaces FULL_CARD / MINIMAL_CARD
SEGMENT_PERSON_CARD  = "PERSON_CARD"      # replaces FILMOGRAPHY_LIST
SEGMENT_ANALYSIS     = "ANALYSIS_TEXT"    # rich essay block
SEGMENT_AWARDS       = "AWARDS_CARD"      # Oscar / IMDB award strip
SEGMENT_TRAILER      = "TRAILER_EMBED"    # YouTube iframe — was only in FULL_CARD branch
SEGMENT_STREAMING    = "STREAMING_STRIP"  # platform badges
SEGMENT_RECS         = "RECOMMENDATION_GRID"
SEGMENT_COMPARISON   = "COMPARISON_TABLE"
SEGMENT_DOWNLOAD     = "DOWNLOAD_CARD"
SEGMENT_SOURCES      = "SOURCES"
SEGMENT_CLARIFY      = "CLARIFICATION"
SEGMENT_TEXT         = "TEXT_ONLY"        # plain prose (always last)

def select_layout_segments(
    primary_intent: str,
    secondary_intents: list[str],
    tool_outputs: dict[str, dict],
    response: dict,
) -> list[str]:
    """
    Returns an ordered list of UI segments.
    First segment is the 'hero' (determines vertical layout anchor).
    Subsequent segments are appended below the hero.
    """
    segments: list[str] = []

    # ── Guard: disambiguation always wins alone ──
    for out in tool_outputs.values():
        if out.get("status") == "disambiguation":
            return [SEGMENT_CLARIFY]

    # ── Guard: illegal download ──
    if primary_intent == "ILLEGAL_DOWNLOAD_REQUEST":
        return [SEGMENT_TEXT]

    # ── Hero segment — what is the response primarily about? ──
    entity_type = response.get("entity_type", "")
    has_poster   = bool(response.get("poster_url"))
    has_awards   = bool(response.get("awards", {}).get("oscar_wins") or 
                        response.get("awards", {}).get("oscar_nominations"))
    has_streaming = bool(response.get("streaming"))
    has_recs      = bool(response.get("recommendations"))
    has_filmography = bool(response.get("filmography"))

    analysis_intents = {
        "FILM_ANALYSIS", "VISUAL_ANALYSIS", "DIRECTOR_ANALYSIS",
        "CONCEPTUAL_EXPLANATION", "THEORETICAL_ANALYSIS",
        "MOVEMENT_OVERVIEW", "HISTORICAL_CONTEXT", "STYLE_COMPARISON",
        "FILM_COMPARISON", "CRITIC_REVIEW", "PLOT_EXPLANATION",
    }

    # Hero: Person card
    if entity_type == "person" or primary_intent in ("PERSON_LOOKUP", "FILMOGRAPHY"):
        segments.append(SEGMENT_PERSON_CARD)

    # Hero: Comparison
    elif primary_intent == "COMPARISON":
        segments.append(SEGMENT_COMPARISON)

    # Hero: Streaming-first (handled before movie-card check so it doesn't get a poster card)
    elif primary_intent == "STREAMING_AVAILABILITY":
        segments.append(SEGMENT_TEXT)
        if has_streaming:
            segments.append(SEGMENT_STREAMING)
        return segments                  # streaming-only, no other segments

    # Hero: Recommendation grid
    elif primary_intent in ("RECOMMENDATION", "TRENDING", "UPCOMING", "TOP_RATED"):
        segments.append(SEGMENT_TEXT)
        if has_recs:
            segments.append(SEGMENT_RECS)
        return segments

    # Hero: Analysis intents — poster anchors the essay, then ANALYSIS_TEXT follows
    elif primary_intent in analysis_intents:
        if has_poster and entity_type == "movie":
            segments.append(SEGMENT_MOVIE_CARD)   # poster acts as visual anchor
        segments.append(SEGMENT_ANALYSIS)          # always include the essay

    # Hero: Movie card (entity lookups, awards, etc. — not analysis, not recs, not streaming)
    elif entity_type == "movie" and has_poster:
        segments.append(SEGMENT_MOVIE_CARD)

    else:
        segments.append(SEGMENT_TEXT)

    # ── Additive panels (attached below the hero) ──
    # Trailer: shown for movie entities whenever trailer_key is present.
    # Intentionally placed after MOVIE_CARD but before awards/streaming so
    # the video anchors engagement before metadata strips appear.
    has_trailer = bool(response.get("trailer_key"))
    if has_trailer and entity_type == "movie" and SEGMENT_TRAILER not in segments:
        # Don't embed trailer for pure recommendation / streaming / award-only queries
        _no_trailer_intents = {"RECOMMENDATION", "TRENDING", "UPCOMING",
                               "TOP_RATED", "STREAMING_AVAILABILITY"}
        if primary_intent not in _no_trailer_intents:
            segments.append(SEGMENT_TRAILER)

    if has_awards and SEGMENT_AWARDS not in segments:
        segments.append(SEGMENT_AWARDS)

    if has_streaming and SEGMENT_STREAMING not in segments:
        segments.append(SEGMENT_STREAMING)

    if has_recs and SEGMENT_RECS not in segments:
        segments.append(SEGMENT_RECS)

    if response.get("download_link"):
        segments.append(SEGMENT_DOWNLOAD)

    if response.get("sources"):
        segments.append(SEGMENT_SOURCES)

    # Always ensure text exists if not already a text-producing segment
    text_producers = {SEGMENT_TEXT, SEGMENT_ANALYSIS, SEGMENT_MOVIE_CARD,
                      SEGMENT_PERSON_CARD, SEGMENT_COMPARISON}
    if not any(s in text_producers for s in segments):
        segments.insert(0, SEGMENT_TEXT)

    return segments

