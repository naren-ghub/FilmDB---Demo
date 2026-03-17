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
ENTITY_LOOKUP, FILM_ANALYSIS, RECOMMENDATION, COMPARISON,
PERSON_LOOKUP, FILMOGRAPHY, PLOT_EXPLANATION,
STREAMING_AVAILABILITY, DOWNLOAD, ILLEGAL_DOWNLOAD_REQUEST,
AWARD_LOOKUP, TRENDING, UPCOMING, TOP_RATED,
BOT_INTERACTION

Classification rules:
- "hi", "hello", "hey", "what is your name", "what can you do", "help me" → BOT_INTERACTION (confidence: 100)
- CRITICAL: If the message mentions ANY movie, person, or film concept, DO NOT use BOT_INTERACTION.
- "tell me about <movie>", "details of <movie>" → ENTITY_LOOKUP
- "tell me about <person>", "who is <person>" → PERSON_LOOKUP
- "analyze <movie>", "critical analysis", "opinion on", "what makes <movie> great", "review of", "critics say about", "cinematic style of", "why is <movie> controversial" → FILM_ANALYSIS
- "what is <film concept>", "explain <theory>", "diegetic vs non-diegetic", "the male gaze in cinema", "auteur theory" → FILM_ANALYSIS
- "Tell me about German Expressionism", "French New Wave", "Italian Neorealism" → FILM_ANALYSIS
- "<movie> vs <movie>", "compare", "which is better" → COMPARISON
- "movies similar to <movie>", "recommend", "suggest films" → RECOMMENDATION
- "filmography of <person>", "movies directed by" → FILMOGRAPHY
- "explain the plot of <movie>" → PLOT_EXPLANATION
- "where can I stream", "what's new on netflix" → STREAMING_AVAILABILITY
- "download <movie>" → DOWNLOAD
- "torrent", "pirated", "cracked" → ILLEGAL_DOWNLOAD_REQUEST
- "oscar", "academy awards", "best picture", "golden globes", "what awards" → AWARD_LOOKUP
- "trending movies", "what's popular" → TRENDING
- "top rated movies" → TOP_RATED
- "upcoming releases" → UPCOMING
- CRITICAL: Movie titles can sound like people's names (e.g. "Marty Supreme", "Mary Poppins"). Prefer ENTITY_LOOKUP unless "who is" or "actor"/"director" is mentioned.
- Always extract mentioned movie titles and person names as entities.
- For COMPARISON: extract BOTH entities.

Entity format: [{"type": "movie"|"person"|"genre"|"year"|"platform", "value": "..."}]

Examples:
- "hi" → {"primary_intent": "BOT_INTERACTION", "secondary_intents": [], "entities": [], "confidence": 100}
- "who is stanley kubrick" → {"primary_intent": "PERSON_LOOKUP", "secondary_intents": [], "entities": [{"type": "person", "value": "Stanley Kubrick"}], "confidence": 95}
- "What is Inception about?" → {"primary_intent": "ENTITY_LOOKUP", "secondary_intents": [], "entities": [{"type": "movie", "value": "Inception"}], "confidence": 95}
- "Why is Kubrick's A Clockwork Orange controversial" → {"primary_intent": "FILM_ANALYSIS", "secondary_intents": [], "entities": [{"type": "movie", "value": "A Clockwork Orange"}, {"type": "person", "value": "Stanley Kubrick"}], "confidence": 90}
- "what do critics say about The Dark Knight" → {"primary_intent": "FILM_ANALYSIS", "secondary_intents": [], "entities": [{"type": "movie", "value": "The Dark Knight"}], "confidence": 95}
- "movies similar to Interstellar" → {"primary_intent": "RECOMMENDATION", "secondary_intents": [], "entities": [{"type": "movie", "value": "Interstellar"}], "confidence": 90}
- "compare Inception and Interstellar" → {"primary_intent": "COMPARISON", "secondary_intents": ["FILM_ANALYSIS"], "entities": [{"type": "movie", "value": "Inception"}, {"type": "movie", "value": "Interstellar"}], "confidence": 95}
- "oscar nominations 2026" → {"primary_intent": "AWARD_LOOKUP", "secondary_intents": [], "entities": [{"type": "year", "value": "2026"}], "confidence": 95}
- "what awards has DiCaprio won" → {"primary_intent": "AWARD_LOOKUP", "secondary_intents": [], "entities": [{"type": "person", "value": "DiCaprio"}], "confidence": 95}
- "explain the plot of Inception" → {"primary_intent": "PLOT_EXPLANATION", "secondary_intents": [], "entities": [{"type": "movie", "value": "Inception"}], "confidence": 95}
- "analyze Antonioni's visual style" → {"primary_intent": "FILM_ANALYSIS", "secondary_intents": [], "entities": [{"type": "person", "value": "Antonioni"}], "confidence": 90}
- "What is the auteur theory?" → {"primary_intent": "FILM_ANALYSIS", "secondary_intents": [], "entities": [], "confidence": 85}
- "is cgi ruining films" → {"primary_intent": "FILM_ANALYSIS", "secondary_intents": [], "entities": [], "confidence": 80}
- "where can I stream The Batman" → {"primary_intent": "STREAMING_AVAILABILITY", "secondary_intents": [], "entities": [{"type": "movie", "value": "The Batman"}], "confidence": 95}
- "stanley kubrick filmography" → {"primary_intent": "FILMOGRAPHY", "secondary_intents": ["PERSON_LOOKUP"], "entities": [{"type": "person", "value": "Stanley Kubrick"}], "confidence": 95}
- "suggest good thriller movies" → {"primary_intent": "RECOMMENDATION", "secondary_intents": [], "entities": [{"type": "genre", "value": "thriller"}], "confidence": 90}

IMPORTANT: Always return confidence >= 70 for any film-related query.
Return confidence 100 for greetings.
"""


INTENT_USER_PROMPT = """
User message: {message}
Return JSON only.
"""


class IntentAgent:
    def __init__(self, primary_llm, secondary_llm=None) -> None:
        self.primary_llm = primary_llm
        self.secondary_llm = secondary_llm
        self.logger = logging.getLogger(__name__)

    def classify(self, message: str) -> dict[str, Any]:
        # Fast-path: detect greetings without an LLM call
        greeting = self._check_greeting(message)
        if greeting:
            if hasattr(self.primary_llm, "last_intent_raw"):
                 self.primary_llm.last_intent_raw = json.dumps(greeting)
            return greeting

        system = INTENT_SYSTEM_PROMPT
        user = INTENT_USER_PROMPT.format(message=message)
        
        # Try primary LLM
        content = self.primary_llm.intent_classify(system, user)
        
        # Fallback to secondary if primary failed (returned empty or errored)
        if not content and self.secondary_llm:
            self.logger.warning("Primary LLM failed, falling back to secondary for intent classification")
            content = self.secondary_llm.intent_classify(system, user)
            
        self.logger.info("IntentAgent raw response: %s", content)
        return self._parse_intent(content)

    def _check_greeting(self, message: str) -> dict[str, Any] | None:
        """Detect simple greetings without using the LLM."""
        text = message.lower().strip().rstrip("!.?")
        greetings = {
            "hi", "hello", "hey", "hii", "hiii", "yo", "sup",
            "good morning", "good afternoon", "good evening",
            "howdy", "what's up", "whats up", "hola",
            "what can you do", "help", "how does this work"
        }
        if text in greetings:
            return {
                "primary_intent": "BOT_INTERACTION",
                "secondary_intents": [],
                "entities": [],
                "confidence": 100,
            }
        return None

    def _parse_intent(self, content: str) -> dict[str, Any]:
        default = {
            "primary_intent": "BOT_INTERACTION",
            "secondary_intents": [],
            "entities": [],
            "confidence": 70,
        }
        if not content:
            return default
        import re
        try:
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
            else:
                data = json.loads(content)
        except json.JSONDecodeError:
            self.logger.warning("Failed to decode JSON from LLM intent: %s", content)
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
        if confidence < 50 and primary not in ("BOT_INTERACTION",):
            confidence = 50

        # Backward compatibility: map deprecated intents to consolidated ones
        _INTENT_COMPAT = {
            "ANALYTICAL_EXPLANATION": "FILM_ANALYSIS",
            "CRITIC_REVIEW":         "FILM_ANALYSIS",
            "REVIEWS":               "FILM_ANALYSIS",
            "MOVIE_SIMILARITY":      "RECOMMENDATION",
            "LEGAL_DOWNLOAD":        "DOWNLOAD",
            "OSCAR_LOOKUP":          "AWARD_LOOKUP",
            "GENERAL_AWARD_LOOKUP":  "AWARD_LOOKUP",
            "OFFICIAL":              "ENTITY_LOOKUP",
            "GREETING":              "BOT_INTERACTION",
            "GENERAL_CONVERSATION":  "BOT_INTERACTION"
        }
        primary = _INTENT_COMPAT.get(primary, primary)
        secondary = [_INTENT_COMPAT.get(s, s) for s in secondary]

        # A.2 — Normalise entity type strings from LLM ("movie_title" → "movie" etc.)
        _TYPE_NORM = {
            "movie_title": "movie", "film": "movie", "movie title": "movie",
            "person_name": "person", "director": "person", "actor": "person",
            "award": "award_event", "award_event": "award_event",
        }
        for ent in entities:
            if isinstance(ent, dict):
                raw = ent.get("type", "").lower().strip()
                ent["type"] = _TYPE_NORM.get(raw, raw)

        return {
            "primary_intent": primary,
            "secondary_intents": secondary,
            "entities": entities,
            "confidence": confidence,
        }
