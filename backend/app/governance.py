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
    "web_search": {
        "name": "web_search",
        "description": "Latest news, reviews, sentiment, box office, and broad search queries, recent events, recently, newly, upcoming",
        "required": ["query"],
    },
    "imdb_trending_tamil": {
        "name": "imdb_trending_tamil",
        "description": "IMDb trending Tamil movies list",
        "required": [],
    },
    "imdb_top_rated_english": {
        "name": "imdb_top_rated_english",
        "description": "IMDb top rated English movies list",
        "required": [],
    },
    "imdb_upcoming": {
        "name": "imdb_upcoming",
        "description": "IMDb upcoming releases by country",
        "required": [],
    },
    "imdb_person": {
        "name": "imdb_person",
        "description": "IMDb personality profile and filmography",
        "required": ["name"],
    },
    "rt_reviews": {
        "name": "rt_reviews",
        "description": "Rotten Tomatoes critics sentiment (score only)",
        "required": ["title"],
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
    max_tools: int = 4,
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
