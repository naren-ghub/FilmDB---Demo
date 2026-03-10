from typing import Any


ROUTING_MATRIX: dict[str, dict[str, list[str]]] = {
    # ── KB-first routes (local data primary, API fallback) ───────────────
    "ENTITY_LOOKUP": {
        "required": ["kb_entity","tmdb"],
        "optional": ["wikipedia"],
        "forbidden": ["archive"],
    },
    "ANALYTICAL_EXPLANATION": {
        "required": ["kb_film_analysis", "kb_critic_review","kb_plot_analysis"],
        "optional": ["wikipedia_service"],
        "forbidden": [],
    },
    "PLOT_EXPLANATION": {
        "required": ["kb_plot_analysis"],
        "optional": ["wikipedia_service"],
        "forbidden": [],
    },
    "CRITIC_REVIEW": {
        "required": ["kb_critic_review","kb_film_analysis"],
        "optional": [], # "cinema_search"
        "forbidden": [],
    },
    "MOVIE_SIMILARITY": {
        "required": ["kb_similarity"],
        "optional": [],
        "forbidden": [],
    },
    "RECOMMENDATION": {
        "required": ["kb_similarity"],
        "optional": [], # "cinema_search"
        "forbidden": [],
    },
    "REVIEWS": {
        "required": ["kb_critic_review"], # "cinema_search"
        "optional": ["wikipedia_service"],
        "forbidden": [],
    },
    "TOP_RATED": {
        "required": ["kb_top_rated","wikipedia_service"],
        "optional": [],
        "forbidden": [],
    },
    "COMPARISON": {
        "required": ["kb_comparison", "kb_filmography","kb_film_analysis","kb_critic_review"],
        "optional": ["wikipedia"], # "cinema_search"
        "forbidden": ["archive"],
    },
    "FILMOGRAPHY": {
        "required": ["kb_filmography", "wikipedia"],
        "optional": ["tmdb"],
        "forbidden": [],
    },
    "PERSON_LOOKUP": {
        "required": ["kb_filmography", "wikipedia"],
        "optional": ["tmdb", "kb_film_analysis"],
        "forbidden": [],
    },
    "FILM_ANALYSIS": {
        "required": ["kb_film_analysis", "kb_critic_review","kb_plot_analysis"],
        "optional": ["wikipedia_service"], # "cinema_search"
        "forbidden": [],
    },
    "STREAMING_AVAILABILITY": {
        "required": ["watchmode"],
        "optional": ["kb_entity_lookup"],
        "forbidden": [],
    },
    "DOWNLOAD": {
        "required": ["archive"],
        "optional": [],
        "forbidden": ["watchmode"],
    },
    "LEGAL_DOWNLOAD": {
        "required": ["archive"],
        "optional": [],
        "forbidden": ["watchmode"],
    },
    "ILLEGAL_DOWNLOAD_REQUEST": {
        "required": [],
        "optional": [],
        "forbidden": ["archive"],
    },
    "UPCOMING": {
        "required": [], # "cinema_search"
        "optional": [],
        "forbidden": [],
    },
    "TRENDING": {
        "required": [], # "cinema_search"
        "optional": [],
        "forbidden": [],
    },
    "OFFICIAL": {
        "required": [], # "cinema_search"
        "optional": ["wikipedia"],
        "forbidden": [],
    },
    "OSCAR_LOOKUP": {
        "required": ["kb_awards", "wikipedia"],
        "optional": [], # "cinema_search"
        "forbidden": ["archive"],
    },
    "GENERAL_AWARD_LOOKUP": {
        "required": ["imdb_awards","kb_awards"],
        "optional": ["wikipedia"],
        "forbidden": ["archive"],
    },
    # ── Non-tool intents ─────────────────────────────────────────────────
    "GREETING": {
        "required": [],
        "optional": [],
        "forbidden": [],
    },
    "GENERAL_CONVERSATION": {
        "required": [],
        "optional": [],
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
    # if isinstance(confidence, int) and confidence < 60:
    #     required.add("cinema_search")

    forbidden -= required
    optional -= forbidden

    return {
        "required": sorted(required),
        "optional": sorted(optional),
        "forbidden": sorted(forbidden),
    }
