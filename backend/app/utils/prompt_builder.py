"""
FilmDB – Prompt Builder
========================
Builds structured prompt components for the LLM.
Returns (system_prompt, user_prompt, context_messages, breakdown) for proper role separation.

Tiered Context Injection:
  - VERIFIED FACTS    → IMDb, TMDB, awards, streaming  (LLM MUST use)
  - CURATED KNOWLEDGE → RAG plots, essays, scripts, recommendations  (LLM SHOULD use)
  - SUPPLEMENTARY     → Wikipedia, web search  (LLM MAY use if relevant)
"""

from __future__ import annotations

# ── Tool Tier Mapping ─────────────────────────────────────────────────────────

TOOL_TIERS: dict[str, str] = {
    # Tier 1: Structured, verified external data — ground truth
    "imdb":                   "VERIFIED_FACTS",
    "imdb_b":                 "VERIFIED_FACTS",
    "tmdb":                   "VERIFIED_FACTS",
    "tmdb_b":                 "VERIFIED_FACTS",
    "imdb_awards":            "VERIFIED_FACTS",
    "oscar_award":            "VERIFIED_FACTS",
    "watchmode":              "VERIFIED_FACTS",
    "archive":                "VERIFIED_FACTS",
    # Tier 2: Curated internal knowledge — scholarly/analytical sources
    "rag":                    "CURATED_KNOWLEDGE",
    "recommendation_engine":  "CURATED_KNOWLEDGE",
    # Tier 3: Supplementary — useful but not authoritative
    "wikipedia":              "SUPPLEMENTARY",
    "wikipedia_b":            "SUPPLEMENTARY",
    "cinema_search":          "SUPPLEMENTARY",
}

_TIER_HEADERS = {
    "VERIFIED_FACTS":    "[VERIFIED FACTS — Always use these values exactly. Never contradict or ignore data in this section.]",
    "CURATED_KNOWLEDGE": "[CURATED KNOWLEDGE — Synthesize this into your analysis. Use to enrich reasoning with depth and scholarly context.]",
    "SUPPLEMENTARY":     "[SUPPLEMENTARY — Use only if directly relevant to the question. You may disregard if it adds no value.]",
}

_DEFAULT_TIER = "SUPPLEMENTARY"


def _get_tier(tool_name: str) -> str:
    """Return the tier for a tool name."""
    if tool_name in TOOL_TIERS:
        return TOOL_TIERS[tool_name]
    # Strip _b suffix for mirrored comparison calls
    base = tool_name[:-2] if tool_name.endswith("_b") else tool_name
    return TOOL_TIERS.get(base, _DEFAULT_TIER)


# ── Main Builder ──────────────────────────────────────────────────────────────

def build_prompt(
    system_instructions: str,
    user_profile: dict | None,
    recent_messages: list[dict[str, str]],
    tool_summaries: list[str],
    user_query: str,
) -> tuple[str, str, list[dict[str, str]], dict[str, int]]:
    """
    Build structured prompt components with tiered context injection.

    Returns:
        (system_prompt, user_prompt, context_messages, breakdown)
    """
    def _est(t: str) -> int:
        return len(t) // 4  # Chars-to-tokens heuristic

    breakdown: dict = {
        "system_core": 0,
        "history":     0,
        "tools":       {},
        "user_query":  _est(user_query),
    }

    # ── System prompt (role="system") ──
    system_parts = [system_instructions.strip()]
    breakdown["system_core"] += _est(system_instructions)

    if user_profile:
        profile_lines = [
            f"- {key}: {value}"
            for key, value in user_profile.items()
            if value not in (None, "", [], {})
        ]
        if profile_lines:
            profile_text = "\n".join(profile_lines)
            system_parts.append(
                "USER CONTEXT (for personalization only — do not let this bias factual answers):\n"
                + profile_text
            )
            breakdown["system_core"] += _est(profile_text)

    system_prompt = "\n\n".join(system_parts)

    # ── Context messages (conversation history) ──
    context_messages: list[dict[str, str]] = []
    for msg in (recent_messages or []):
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content:
            context_messages.append({"role": role, "content": content})
            breakdown["history"] += _est(content)

    # ── User prompt: tiered reference data + query ──
    user_parts: list[str] = []

    if tool_summaries:
        tier_buckets: dict[str, list[str]] = {
            "VERIFIED_FACTS":    [],
            "CURATED_KNOWLEDGE": [],
            "SUPPLEMENTARY":     [],
        }

        for s in tool_summaries:
            if not s or "not_found" in s.lower()[:40]:
                continue  # skip empty / failed results

            # Extract tool name from summary prefix: "tool_name: ..."
            tool_name = s.split(":")[0].strip() if ":" in s else "data"
            tier = _get_tier(tool_name)

            wrapped = f"[{tool_name}]\n{s}\n[/{tool_name}]"
            tier_buckets[tier].append(wrapped)
            breakdown["tools"][tool_name] = _est(s)

        # Emit non-empty tiers in priority order
        tier_sections: list[str] = []
        for tier in ("VERIFIED_FACTS", "CURATED_KNOWLEDGE", "SUPPLEMENTARY"):
            if tier_buckets[tier]:
                header = _TIER_HEADERS[tier]
                body = "\n".join(tier_buckets[tier])
                tier_sections.append(f"{header}\n{body}")

        if tier_sections:
            user_parts.append("REFERENCE DATA:\n\n" + "\n\n".join(tier_sections))

    user_parts.append(user_query.strip())
    user_prompt = "\n\n".join(user_parts)

    return system_prompt, user_prompt, context_messages, breakdown
