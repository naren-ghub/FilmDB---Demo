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
  "confidence": 85
}

Valid primary intents:
ENTITY_LOOKUP, ANALYTICAL_EXPLANATION, AVAILABILITY, RECOMMENDATION, DOWNLOAD,
LEGAL_DOWNLOAD, ILLEGAL_DOWNLOAD_REQUEST, STREAMING_AVAILABILITY,
REVIEWS, TRENDING, UPCOMING, TOP_RATED, STREAMING_DISCOVERY, COMPARISON,
PERSON_LOOKUP, AWARD_LOOKUP, GREETING, GENERAL_CONVERSATION

Classification rules:
- "hi", "hello", "hey", greetings → GREETING (confidence: 100)
- General chat, opinions, philosophy, non-specific film talk → GENERAL_CONVERSATION (confidence: 80)
- "tell me about <movie>" → ENTITY_LOOKUP
- "tell me about <person>" → PERSON_LOOKUP
- "where can I watch <movie>" → STREAMING_AVAILABILITY
- "movies similar to <movie>" → RECOMMENDATION
- "trending movies", "what's popular" → TRENDING
- "top rated movies" → TOP_RATED
- "upcoming releases" → UPCOMING
- "oscar", "nominations", "awards" → AWARD_LOOKUP
- "review of <movie>" → REVIEWS
- "what's new on netflix" → STREAMING_DISCOVERY
- "download <movie>" → DOWNLOAD
- When a specific movie title is mentioned → always extract it as an entity
- When a specific person name is mentioned → always extract it as an entity

Entity format: [{"type": "movie"|"person"|"genre"|"year"|"platform", "value": "..."}]

Examples:
- "hi" → {"primary_intent": "GREETING", "secondary_intents": [], "entities": [], "confidence": 100}
- "What is Inception about?" → {"primary_intent": "ENTITY_LOOKUP", "secondary_intents": [], "entities": [{"type": "movie", "value": "Inception"}], "confidence": 95}
- "who is Christopher Nolan" → {"primary_intent": "PERSON_LOOKUP", "secondary_intents": [], "entities": [{"type": "person", "value": "Christopher Nolan"}], "confidence": 95}
- "trending tamil movies" → {"primary_intent": "TRENDING", "secondary_intents": [], "entities": [], "confidence": 95}
- "top rated english films" → {"primary_intent": "TOP_RATED", "secondary_intents": [], "entities": [], "confidence": 95}
- "upcoming releases" → {"primary_intent": "UPCOMING", "secondary_intents": [], "entities": [], "confidence": 95}
- "where can I stream The Batman" → {"primary_intent": "STREAMING_AVAILABILITY", "secondary_intents": [], "entities": [{"type": "movie", "value": "The Batman"}], "confidence": 95}
- "oscar nominations 2026" → {"primary_intent": "AWARD_LOOKUP", "secondary_intents": [], "entities": [{"type": "year", "value": "2026"}], "confidence": 95}
- "movies like Interstellar" → {"primary_intent": "RECOMMENDATION", "secondary_intents": [], "entities": [{"type": "movie", "value": "Interstellar"}], "confidence": 90}
- "what are the current trending films" → {"primary_intent": "TRENDING", "secondary_intents": [], "entities": [], "confidence": 95}
- "stanley kubrick filmography" → {"primary_intent": "PERSON_LOOKUP", "secondary_intents": [], "entities": [{"type": "person", "value": "Stanley Kubrick"}], "confidence": 95}
- "give overview of kottukkali" → {"primary_intent": "ENTITY_LOOKUP", "secondary_intents": [], "entities": [{"type": "movie", "value": "Kottukkali"}], "confidence": 90}
- "suggest good movies released past 2 weeks" → {"primary_intent": "TRENDING", "secondary_intents": ["RECOMMENDATION"], "entities": [], "confidence": 90}
- "Why is Kubrick's A Clockwork Orange controversial" → {"primary_intent": "ANALYTICAL_EXPLANATION", "secondary_intents": ["ENTITY_LOOKUP"], "entities": [{"type": "movie", "value": "A Clockwork Orange"}, {"type": "person", "value": "Stanley Kubrick"}], "confidence": 90}

IMPORTANT: Always return confidence >= 70 for any film-related query.
Return confidence 100 for greetings.
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
        # Fast-path: detect greetings without an LLM call
        greeting = self._check_greeting(message)
        if greeting:
            self.llm.last_intent_raw = json.dumps(greeting)
            return greeting

        system = INTENT_SYSTEM_PROMPT
        user = INTENT_USER_PROMPT.format(message=message)
        content = self.llm.intent_classify(system, user)
        self.logger.info("IntentAgent raw response: %s", content)
        return self._parse_intent(content)

    def _check_greeting(self, message: str) -> dict[str, Any] | None:
        """Detect simple greetings without using the LLM."""
        text = message.lower().strip().rstrip("!.?")
        greetings = {
            "hi", "hello", "hey", "hii", "hiii", "yo", "sup",
            "good morning", "good afternoon", "good evening",
            "howdy", "what's up", "whats up", "hola",
        }
        if text in greetings:
            return {
                "primary_intent": "GREETING",
                "secondary_intents": [],
                "entities": [],
                "confidence": 100,
            }
        return None

    def _parse_intent(self, content: str) -> dict[str, Any]:
        default = {
            "primary_intent": "GENERAL_CONVERSATION",
            "secondary_intents": [],
            "entities": [],
            "confidence": 70,
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
        confidence = data.get("confidence", 70)

        if not isinstance(primary, str):
            primary = default["primary_intent"]
        if not isinstance(secondary, list):
            secondary = []
        if not isinstance(entities, list):
            entities = []
        if isinstance(confidence, float):
            if 0 < confidence <= 1:
                confidence = int(confidence * 100)
            else:
                confidence = int(confidence)
        if not isinstance(confidence, int):
            confidence = 70

        # Ensure minimum confidence for any valid intent
        if confidence < 50 and primary not in ("GREETING", "GENERAL_CONVERSATION"):
            confidence = 50

        return {
            "primary_intent": primary,
            "secondary_intents": secondary,
            "entities": entities,
            "confidence": confidence,
        }
