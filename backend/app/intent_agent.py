import json
import logging
from typing import Any

from app.llm.groq_client import GroqClient


INTENT_SYSTEM_PROMPT = """
You are the FilmDB IntentAgent. Return STRICT JSON ONLY.
No markdown. No extra text. No explanations outside JSON.

Classify the user's primary intent, any secondary intents, and extract entities.
Entities are specific items mentioned in the query (movie titles, people, genres, years).

Schema:
{
  "primary_intent": "INTENT_NAME",
  "secondary_intents": [],
  "entities": [],
  "confidence": 0
}

Valid primary intents:
ENTITY_LOOKUP, ANALYTICAL_EXPLANATION, AVAILABILITY, RECOMMENDATION, DOWNLOAD,
LEGAL_DOWNLOAD, ILLEGAL_DOWNLOAD_REQUEST, STREAMING_AVAILABILITY,
REVIEWS, TRENDING, UPCOMING, TOP_RATED, STREAMING_DISCOVERY, COMPARISON,
PERSON_LOOKUP, AWARD_LOOKUP

Examples (intent mapping):
- "what are trending films" -> TRENDING
- "oscar nominations 2026" -> TRENDING
- "recent releases this week" -> TRENDING
- "who won best picture 2024" -> TRENDING
- "top rated english films" -> TOP_RATED
- "upcoming tamil releases" -> UPCOMING
- "what's new on netflix" -> STREAMING_DISCOVERY
- "tell me about christopher nolan" -> PERSON_LOOKUP
- "oscar nominations 2026" -> AWARD_LOOKUP
- "download the godfather movie" -> ILLEGAL_DOWNLOAD_REQUEST
"""


INTENT_USER_PROMPT = """
User message: {message}
Return JSON only.
"""


class IntentAgent:
    def __init__(self, llm: GroqClient) -> None:
        self.llm = llm
        self.logger = logging.getLogger(__name__)

    def classify(self, message: str) -> dict[str, Any]:
        system = INTENT_SYSTEM_PROMPT
        user = INTENT_USER_PROMPT.format(message=message)
        content = self.llm.intent_classify(system, user)
        self.logger.info("IntentAgent raw response: %s", content)
        return self._parse_intent(content)

    def _parse_intent(self, content: str) -> dict[str, Any]:
        default = {
            "primary_intent": "ENTITY_LOOKUP",
            "secondary_intents": [],
            "entities": [],
            "confidence": 0,
        }
        if not content:
            return default
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return default

        if not isinstance(data, dict):
            return default
        primary = data.get("primary_intent", default["primary_intent"])
        secondary = data.get("secondary_intents", [])
        entities = data.get("entities", [])
        confidence = data.get("confidence", 0)

        if not isinstance(primary, str):
            primary = default["primary_intent"]
        if not isinstance(secondary, list):
            secondary = []
        if not isinstance(entities, list):
            entities = []
        if isinstance(confidence, float):
            if 0 <= confidence <= 1:
                confidence = int(confidence * 100)
            else:
                confidence = int(confidence)
        if not isinstance(confidence, int):
            confidence = 0

        return {
            "primary_intent": primary,
            "secondary_intents": secondary,
            "entities": entities,
            "confidence": confidence,
        }
