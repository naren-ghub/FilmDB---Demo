from typing import Any


ROUTING_MATRIX: dict[str, dict[str, list[str]]] = {
    # ── KB-first routes (local data primary, API fallback) ───────────────
    "ENTITY_LOOKUP": {
        "required": ["kb_entity"],
        "optional": ["imdb", "wikipedia", "watchmode"],
        "forbidden": ["archive"],
    },
    "ANALYTICAL_EXPLANATION": {
        "required": ["kb_entity", "kb_plot"],
        "optional": ["wikipedia", "web_search"],
        "forbidden": ["archive"],
    },
    "PLOT_EXPLANATION": {
        "required": ["kb_plot"],
        "optional": ["kb_entity", "wikipedia"],
        "forbidden": [],
    },
    "CRITIC_SUMMARY": {
        "required": ["kb_critic"],
        "optional": ["kb_entity", "rt_reviews", "web_search"],
        "forbidden": [],
    },
    "MOVIE_SIMILARITY": {
        "required": ["kb_similarity"],
        "optional": ["similarity"],
        "forbidden": [],
    },
    "RECOMMENDATION": {
        "required": ["kb_similarity"],
        "optional": ["similarity", "web_search"],
        "forbidden": [],
    },
    "REVIEWS": {
        "required": ["kb_critic"],
        "optional": ["rt_reviews", "web_search"],
        "forbidden": [],
    },
    "TOP_RATED": {
        "required": ["kb_top_rated"],
        "optional": ["imdb_top_rated_english"],
        "forbidden": [],
    },
    "COMPARISON": {
        "required": ["kb_comparison"],
        "optional": ["web_search"],
        "forbidden": ["archive"],
    },
    "FILMOGRAPHY": {
        "required": ["kb_filmography"],
        "optional": ["imdb_person", "wikipedia"],
        "forbidden": [],
    },
    "PERSON_LOOKUP": {
        "required": ["kb_filmography"],
        "optional": ["imdb_person", "wikipedia", "web_search"],
        "forbidden": [],
    },
    # ── API-first routes (live data required) ────────────────────────────
    "AVAILABILITY": {
        "required": ["watchmode"],
        "optional": ["web_search"],
        "forbidden": [],
    },
    "STREAMING_AVAILABILITY": {
        "required": ["watchmode"],
        "optional": ["web_search"],
        "forbidden": [],
    },
    "DOWNLOAD": {
        "required": ["watchmode"],
        "optional": ["web_search"],
        "forbidden": ["archive"],
    },
    "LEGAL_DOWNLOAD": {
        "required": ["watchmode"],
        "optional": ["web_search"],
        "forbidden": ["archive"],
    },
    "ILLEGAL_DOWNLOAD_REQUEST": {
        "required": [],
        "optional": [],
        "forbidden": ["archive"],
    },
    "TRENDING": {
        "required": ["web_search", "imdb_trending_tamil"],
        "optional": [],
        "forbidden": [],
    },
    "OFFICIAL": {
        "required": ["web_search"],
        "optional": ["wikipedia"],
        "forbidden": [],
    },
    "UPCOMING": {
        "required": ["imdb_upcoming"],
        "optional": ["web_search"],
        "forbidden": [],
    },
    "AWARD_LOOKUP": {
        "required": ["wikipedia", "web_search"],
        "optional": ["imdb"],
        "forbidden": ["archive"],
    },
    "STREAMING_DISCOVERY": {
        "required": ["web_search"],
        "optional": [],
        "forbidden": [],
    },
    # ── Non-tool intents ─────────────────────────────────────────────────
    "GREETING": {
        "required": [],
        "optional": [],
        "forbidden": [],
    },
    "GENERAL_CONVERSATION": {
        "required": ["web_search"],
        "optional": ["wikipedia"],
        "forbidden": [],
    },
}


def build_tool_plan(intent: dict[str, Any], planner_tools: list[dict]) -> dict[str, list[str]]:
    primary = intent.get("primary_intent", "GENERAL_CONVERSATION")
    secondary = intent.get("secondary_intents", [])
    intents = [primary] + [i for i in secondary if isinstance(i, str)]
    confidence = intent.get("confidence", 100)

    required: set[str] = set()
    optional: set[str] = set()
    forbidden: set[str] = set()

    for intent_name in intents:
        policy = ROUTING_MATRIX.get(intent_name)
        if not policy:
            # Unknown intent → fallback to web_search
            policy = ROUTING_MATRIX["GENERAL_CONVERSATION"]
        required.update(policy.get("required", []))
        optional.update(policy.get("optional", []))
        forbidden.update(policy.get("forbidden", []))

    planner_names = {
        str(t.get("name")) for t in planner_tools if isinstance(t, dict) and t.get("name")
    }
    optional.update(planner_names)

    # Low confidence → add web_search as safety net
    if isinstance(confidence, int) and confidence < 60:
        required.add("web_search")

    forbidden -= required
    optional -= forbidden

    return {
        "required": sorted(required),
        "optional": sorted(optional),
        "forbidden": sorted(forbidden),
    }
