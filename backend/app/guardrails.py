from typing import Any


def should_block(intent: dict[str, Any], message: str, has_context: bool) -> tuple[bool, str]:
    # Block illegal download requests
    if intent.get("primary_intent") == "ILLEGAL_DOWNLOAD_REQUEST":
        return True, "I can't help with illegal downloads. I can help find legal streaming options."

    # Block pronoun-only queries that lack session context
    if _is_pronoun_only(message) and not has_context:
        return True, "I need the specific movie or person name to proceed."

    # Block empty intent (should never happen with defaults)
    if not intent.get("primary_intent"):
        return True, "I couldn't determine your intent. Can you clarify?"

    # NOTE: We no longer block on low confidence.
    # Low confidence queries are handled by the routing matrix
    # which adds web_search as a fallback tool.
    return False, ""


def _is_pronoun_only(message: str) -> bool:
    text = message.lower().strip()
    pronouns = ["him", "her", "it", "that", "this", "they", "them"]
    return len(text.split()) <= 4 and any(p in text for p in pronouns)
