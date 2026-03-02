from typing import Any


ROUTING_MATRIX: dict[str, dict[str, list[str]]] = {
    "ENTITY_LOOKUP": {
        "required": ["imdb"],
        "optional": ["wikipedia", "watchmode"],
        "forbidden": ["archive"],
    },
    "ANALYTICAL_EXPLANATION": {
        "required": ["imdb", "wikipedia"],
        "optional": ["web_search"],
        "forbidden": ["archive"],
    },
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
    "RECOMMENDATION": {
        "required": ["similarity"],
        "optional": ["imdb", "web_search"],
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
    "REVIEWS": {
        "required": ["rt_reviews"],
        "optional": ["imdb", "web_search", "wikipedia"],
        "forbidden": [],
    },
    "TRENDING": {
        "required": ["imdb_trending_tamil", "web_search"],
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
        "required": ["web_search"],
        "optional": ["wikipedia"],
        "forbidden": ["archive"],
    },
    "TOP_RATED": {
        "required": ["imdb_top_rated_english"],
        "optional": ["web_search"],
        "forbidden": [],
    },
    "STREAMING_DISCOVERY": {
        "required": ["web_search"],
        "optional": [],
        "forbidden": [],
    },
    "PERSON_LOOKUP": {
        "required": ["imdb_person", "wikipedia"],
        "optional": ["web_search"],
        "forbidden": [],
    },
    "COMPARISON": {
        "required": ["web_search"],
        "optional": ["imdb", "wikipedia"],
        "forbidden": ["archive"],
    },
    # ── New intents ──
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
