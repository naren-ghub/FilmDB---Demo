"""
FilmDB – Prompt Builder
========================
Builds structured prompt components for the LLM.
Returns (system_prompt, user_prompt, context_messages) for proper role separation.
"""


def build_prompt(
    system_instructions: str,
    user_profile: dict | None,
    recent_messages: list[dict[str, str]],
    tool_summaries: list[str],
    user_query: str,
) -> tuple[str, str, list[dict[str, str]]]:
    """
    Build structured prompt components for generate_response().

    Returns:
        (system_prompt, user_prompt, context_messages)
    """
    # ── System prompt (role="system") ──
    system_parts = [system_instructions.strip()]

    if user_profile:
        profile_lines = []
        for key, value in user_profile.items():
            if value in (None, "", [], {}):
                continue
            profile_lines.append(f"- {key}: {value}")
        if profile_lines:
            system_parts.append(
                "USER CONTEXT (for personalization only, "
                "do not let this bias factual answers):\n"
                + "\n".join(profile_lines)
            )

    system_prompt = "\n\n".join(system_parts)

    # ── Context messages (role="user"/"assistant" pairs) ──
    context_messages: list[dict[str, str]] = []
    if recent_messages:
        for msg in recent_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                context_messages.append({"role": role, "content": content})

    # ── User prompt (role="user") ──
    user_parts = []

    if tool_summaries:
        # Filter out empty / not_found tool results
        useful = [s for s in tool_summaries if s and "not_found" not in s.lower()[:40]]
        if useful:
            wrapped = [f"[TOOL: {s.split(':')[0].strip() if ':' in s else 'data'}]\n{s}\n[/TOOL]"
                        for s in useful]
            user_parts.append("REFERENCE DATA (use these facts as ground truth):\n"
                              + "\n".join(wrapped))

    user_parts.append(user_query.strip())
    user_prompt = "\n\n".join(user_parts)

    return system_prompt, user_prompt, context_messages
