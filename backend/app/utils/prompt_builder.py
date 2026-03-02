

def build_prompt(
    system_instructions: str,
    user_profile: dict | None,
    recent_messages: list[dict[str, str]],
    tool_summaries: list[str],
    user_query: str,
) -> str:
    sections = []
    sections.append("SYSTEM:\n" + system_instructions.strip())

    if user_profile:
        profile_lines = []
        for key, value in user_profile.items():
            if value in (None, "", [], {}):
                continue
            profile_lines.append(f"- {key}: {value}")
        if profile_lines:
            sections.append("USER PROFILE:\n" + "\n".join(profile_lines))

    if recent_messages:
        convo_lines = []
        for msg in recent_messages:
            role = msg.get("role")
            content = msg.get("content")
            convo_lines.append(f"{role}: {content}")
        sections.append("RECENT CONVERSATION:\n" + "\n".join(convo_lines))

    if tool_summaries:
        wrapped = [f"[TOOL_DATA] {summary} [/TOOL_DATA]" for summary in tool_summaries]
        sections.append("TOOL DATA:\n" + "\n".join(wrapped))

    sections.append("USER QUERY:\n" + user_query.strip())

    return "\n\n".join(sections)
