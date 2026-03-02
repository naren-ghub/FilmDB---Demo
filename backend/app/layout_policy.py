from typing import Any


def select_response_mode(
    primary_intent: str, secondary_intents: list[str], tool_outputs: dict[str, dict]
) -> str:
    watchmode = tool_outputs.get("watchmode", {})
    similarity = tool_outputs.get("similarity", {})
    has_streaming = (
        watchmode.get("status") == "success"
        and bool(watchmode.get("data", {}).get("platforms"))
    )
    has_recs = (
        similarity.get("status") == "success"
        and bool(similarity.get("data", {}).get("recommendations"))
    )

    if primary_intent == "AVAILABILITY":
        return "AVAILABILITY_FOCUS"
    if primary_intent == "STREAMING_AVAILABILITY":
        return "AVAILABILITY_FOCUS"
    if primary_intent == "RECOMMENDATION":
        return "RECOMMENDATION_GRID"
    if primary_intent == "ANALYTICAL_EXPLANATION":
        return "EXPLANATION_PLUS_AVAILABILITY" if has_streaming else "EXPLANATION_ONLY"
    if primary_intent == "ENTITY_LOOKUP":
        return "FULL_CARD" if tool_outputs.get("imdb") else "MINIMAL_CARD"
    if primary_intent == "REVIEWS":
        return "EXPLANATION_PLUS_AVAILABILITY" if has_streaming else "EXPLANATION_ONLY"
    if primary_intent == "TRENDING":
        return "RECOMMENDATION_GRID"
    if primary_intent == "UPCOMING":
        return "RECOMMENDATION_GRID"
    if primary_intent == "TOP_RATED":
        return "RECOMMENDATION_GRID"
    if primary_intent == "STREAMING_DISCOVERY":
        return "RECOMMENDATION_GRID"
    if primary_intent == "DOWNLOAD":
        return "MINIMAL_CARD"
    if primary_intent == "LEGAL_DOWNLOAD":
        return "MINIMAL_CARD"
    if primary_intent == "ILLEGAL_DOWNLOAD_REQUEST":
        return "EXPLANATION_ONLY"
    if primary_intent == "PERSON_LOOKUP":
        return "FULL_CARD"
    if primary_intent == "AWARD_LOOKUP":
        has_list = False
        for key in ("imdb_trending_tamil", "imdb_top_rated_english", "imdb_upcoming"):
            output = tool_outputs.get(key)
            if output and output.get("status") == "success":
                movies = output.get("data", {}).get("movies", [])
                if movies:
                    has_list = True
                    break
        return "RECOMMENDATION_GRID" if has_list else "EXPLANATION_ONLY"
    if primary_intent in ("GREETING", "GENERAL_CONVERSATION"):
        return "EXPLANATION_ONLY"

    if "AVAILABILITY" in secondary_intents and has_streaming:
        return "EXPLANATION_PLUS_AVAILABILITY"
    if "RECOMMENDATION" in secondary_intents and has_recs:
        return "RECOMMENDATION_GRID"

    return "EXPLANATION_ONLY"
