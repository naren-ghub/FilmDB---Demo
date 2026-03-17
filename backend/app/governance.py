import logging
import re
from typing import Any, Literal, Sequence, overload

TOOL_REGISTRY = {
    "imdb": {
        "name": "imdb",
        "description": "Fetch movie metadata, ratings, cast, release year, poster",
        "required": ["title"],
    },
    "wikipedia": {
        "name": "wikipedia",
        "description": "Overview, biography, historical context",
        "required": ["title"],
    },
    "watchmode": {
        "name": "watchmode",
        "description": "Streaming availability",
        "required": ["title"],
    },
    "similarity": {
        "name": "similarity",
        "description": "Content-based recommendations",
        "required": ["title"],
    },
    "archive": {
        "name": "archive",
        "description": "Legal public domain download",
        "required": ["title"],
    },


    "imdb_awards": {
        "name": "imdb_awards",
        "description": "IMDb awards and nominations for a movie",
        "required": [],
    },

    # ── KB-powered tools ─────────────────────────────────────────────
    "kb_entity": {
        "name": "kb_entity",
        "description": "KB movie entity lookup (local data)",
        "required": ["title"],
    },
    "kb_plot": {
        "name": "kb_plot",
        "description": "KB Wikipedia plot retrieval",
        "required": ["title"],
    },
    "kb_similarity": {
        "name": "kb_similarity",
        "description": "KB tag-based movie similarity",
        "required": ["title"],
    },
    "kb_top_rated": {
        "name": "kb_top_rated",
        "description": "KB top rated movies (genre/year/language filters)",
        "required": [],
    },
    "kb_filmography": {
        "name": "kb_filmography",
        "description": "KB person filmography lookup",
        "required": ["name"],
    },
    "kb_comparison": {
        "name": "kb_comparison",
        "description": "KB side-by-side movie comparison",
        "required": ["title_a", "title_b"],
    },
    "kb_awards": {
        "name": "kb_awards",
        "description": "KB local Oscar nominations and wins for a movie or person",
        "required": [],
    },

    # ── Semantic RAG tools ─────────────────────────────────────────────
    "rag_essays": {
        "name": "rag_essays",
        "description": (
            "Semantic RAG retrieval over film analysis essays (Senses of Cinema, BFI). "
            "Use for questions about directors, cinematic style, critical significance, "
            "film appreciation, and 'why is X great' queries."
        ),
        "required": ["query"],
    },
    "rag_books": {
        "name": "rag_books",
        "description": (
            "Semantic RAG retrieval over 318 classified cinema books "
            "(film theory, criticism, history, aesthetics, production, scripts). "
            "Use for conceptual questions, theoretical analysis, techniques, and historical context."
        ),
        "required": ["query", "domain"],  # domain: film_theory|film_criticism|film_history|film_aesthetics|film_production|scripts
    },
    "rag_scripts": {
        "name": "rag_scripts",
        "description": (
            "Semantic RAG retrieval over movie screenplays and scripts. "
            "Use when the user asks about dialogue, scenes, or script structure "
            "for a specific movie or person."
        ),
        "required": ["query"],
    },
}


def _missing_required(arguments: dict, required: Sequence[str]) -> list[str]:
    missing = []
    for key in required:
        if key not in arguments or arguments.get(key) in (None, ""):
            missing.append(key)
    return missing


logger = logging.getLogger(__name__)


def validate_tool_call(tool_call: dict[str, Any]) -> tuple[bool, str]:
    name = tool_call.get("name")
    if name not in TOOL_REGISTRY:
        return False, "tool_not_registered"
    arguments = tool_call.get("arguments", {})
    missing = _missing_required(arguments, TOOL_REGISTRY[name]["required"])
    if missing:
        return False, f"missing_required: {','.join(missing)}"
    return True, "ok"


@overload
def filter_tool_calls(
    user_message: str,
    tool_calls: list[dict[str, Any]],
    max_tools: int = 4,
    return_rejections: Literal[False] = False,
) -> list[dict[str, Any]]: ...


@overload
def filter_tool_calls(
    user_message: str,
    tool_calls: list[dict[str, Any]],
    max_tools: int,
    return_rejections: Literal[True],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]: ...


@overload
def filter_tool_calls(
    user_message: str,
    tool_calls: list[dict[str, Any]],
    *,
    return_rejections: Literal[True],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]: ...


def filter_tool_calls(
    user_message: str,
    tool_calls: list[dict[str, Any]],
    max_tools: int = 5,
    return_rejections: bool = False,
) -> list[dict[str, Any]] | tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    approved: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen = set()
    for call in tool_calls:
        if not isinstance(call, dict):
            rejected.append({"name": None, "reason": "not_a_dict"})
            continue
        if len(approved) >= max_tools:
            rejected.append({"name": call.get("name"), "reason": "max_tools_reached"})
            continue
        valid, reason = validate_tool_call(call)
        if not valid:
            logger.debug(f"Rejected invalid tool call {call.get('name')}: {reason}")
            rejected.append({"name": call.get("name"), "reason": reason})
            continue
        name = call.get("name")
        if not name:
            rejected.append({"name": None, "reason": "missing_name"})
            continue
        signature = f"{name}:{call.get('arguments')}"
        if signature in seen:
            rejected.append({"name": name, "reason": "duplicate"})
            continue
        seen.add(signature)
        approved.append(call)
    if return_rejections:
        return approved, rejected
    return approved
