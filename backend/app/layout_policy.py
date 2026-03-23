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
