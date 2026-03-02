from typing import Any


ROUTING_MATRIX: dict[str, dict[str, list[str]]] = {
    "ENTITY_LOOKUP": {
        "required": ["imdb"],
        "optional": ["wikipedia"],
        "forbidden": ["archive"],
    },
    "ANALYTICAL_EXPLANATION": {
        "required": ["imdb"],
        "optional": ["web_search","wikipedia"],
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
    "REVIEWS": {
        "required": ["rt_reviews"],
        "optional": ["web_search", "wikipedia"],
        "forbidden": [],
    },
    "TRENDING": {
        "required": ["imdb_trending_tamil"],
        "optional": ["web_search"],
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
        "forbidden": ["imdb", "archive"],
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
        "required": ["imdb_person"],
        "optional": ["web_search", "wikipedia"],
        "forbidden": [],
    },
    "COMPARISON": {
        "required": ["web_search"],
        "optional": ["wikipedia"],
        "forbidden": ["archive"],
    },
}


def build_tool_plan(intent: dict[str, Any], planner_tools: list[dict]) -> dict[str, list[str]]:
    primary = intent.get("primary_intent", "ENTITY_LOOKUP")
    secondary = intent.get("secondary_intents", [])
    intents = [primary] + [i for i in secondary if isinstance(i, str)]
    confidence = intent.get("confidence", 100)

    required: set[str] = set()
    optional: set[str] = set()
    forbidden: set[str] = set()

    for intent_name in intents:
        policy = ROUTING_MATRIX.get(intent_name, ROUTING_MATRIX["ENTITY_LOOKUP"])
        required.update(policy.get("required", []))
        optional.update(policy.get("optional", []))
        forbidden.update(policy.get("forbidden", []))

    planner_names = {
        str(t.get("name")) for t in planner_tools if isinstance(t, dict) and t.get("name")
    }
    optional.update(planner_names)

    if isinstance(confidence, int) and confidence < 35:
        required.add("web_search")

    forbidden -= required
    optional -= forbidden

    return {
        "required": sorted(required),
        "optional": sorted(optional),
        "forbidden": sorted(forbidden),
    }
