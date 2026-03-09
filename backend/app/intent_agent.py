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
PERSON_LOOKUP, AWARD_LOOKUP, GREETING, GENERAL_CONVERSATION,
PLOT_EXPLANATION, CRITIC_SUMMARY, MOVIE_SIMILARITY, FILMOGRAPHY, FILM_ANALYSIS

Classification rules:
- "hi", "hello", "hey", greetings → GREETING (confidence: 100)
- "what is your name", "what can you do", general social talk → GENERAL_CONVERSATION (confidence: 80)
- CRITICAL: If the message mentions ANY movie, person, or specific film concept, DO NOT use GENERAL_CONVERSATION. Use specific intents like ENTITY_LOOKUP, FILM_ANALYSIS, etc.
- "<movie> or <movie>", "which is better <movie> or <movie>", "opinion on <movie> vs <movie>" → COMPARISON (with secondary FILM_ANALYSIS, CRITIC_SUMMARY, PLOT_EXPLANATION)
- "who is better <person> or <person>", "comparison between <person> and <person>", "<person> vs <person>" → COMPARISON (with secondary FILM_ANALYSIS)
- "compare <movie> and <movie>" → COMPARISON
- "tell me about <movie>", "details of <movie>" → ENTITY_LOOKUP
- "tell me about <person>", "who is <person>" → PERSON_LOOKUP
- "analyze <movie>", "film analysis of <movie>", "critical analysis", "opinion on <movie>" → FILM_ANALYSIS
- "cinematic style of <director>", "what makes <director> unique" → FILM_ANALYSIS
- CRITICAL: Movie titles can sound like people's names (e.g. "Marty Supreme", "Mary Poppins", "The Godfather"). If a query is "tell me about X", and X could be a movie title, prefer ENTITY_LOOKUP unless the user explicitly mentions "actor", "director", or "who is".
- "interstellar movie card", "show me the poster for avatar", "details of matrix" → ENTITY_LOOKUP
- "movies similar to <movie>" → MOVIE_SIMILARITY
- "trending movies", "what's popular" → TRENDING
- "top rated movies" → TOP_RATED
- "upcoming releases" → UPCOMING
- "oscar", "nominations", "awards" → AWARD_LOOKUP
- "review of <movie>", "what do critics say about <movie>" → CRITIC_SUMMARY
- "what's new on netflix" → STREAMING_DISCOVERY
- "download <movie>" → DOWNLOAD
- "explain the plot of <movie>", "plot of <movie>" → PLOT_EXPLANATION
- "filmography of <person>", "movies directed by <person>" → FILMOGRAPHY
- When a specific movie title is mentioned → always extract it as an entity
- When a specific person name is mentioned → always extract it as an entity
- For COMPARISON: extract BOTH movie or person entities
- CRITICAL: If the user explicitly asks for a "movie card", "poster", or "details", you MUST classify it as ENTITY_LOOKUP. Do NOT fall back to GENERAL_CONVERSATION.

Entity format: [{"type": "movie"|"person"|"genre"|"year"|"platform", "value": "..."}]

Examples:
- "hi" → {"primary_intent": "GREETING", "secondary_intents": [], "entities": [], "confidence": 100}
- "who is stanley kubrick", "who is miyazaki" → {"primary_intent": "PERSON_LOOKUP", "secondary_intents": [], "entities": [{"type": "person", "value": "Stanley Kubrick"}], "confidence": 95}
- "What is Inception about?", "give overview of kottukkali" → {"primary_intent": "ENTITY_LOOKUP", "secondary_intents": [], "entities": [{"type": "movie", "value": "Inception"}], "confidence": 95}
- "interstellar movie card", "show me the poster for avatar", "details of matrix" → {"primary_intent": "ENTITY_LOOKUP", "secondary_intents": [], "entities": [{"type": "movie", "value": "Interstellar"}], "confidence": 95}
- "Why is Kubrick's A Clockwork Orange controversial" → {"primary_intent": "ANALYTICAL_EXPLANATION", "secondary_intents": ["ENTITY_LOOKUP"], "entities": [{"type": "movie", "value": "A Clockwork Orange"}, {"type": "person", "value": "Stanley Kubrick"}], "confidence": 90}
- "where can I stream The Batman" → {"primary_intent": "STREAMING_AVAILABILITY", "secondary_intents": ["AVAILABILITY"], "entities": [{"type": "movie", "value": "The Batman"}], "confidence": 95}
- "movies similar to Interstellar" → {"primary_intent": "MOVIE_SIMILARITY", "secondary_intents": ["RECOMMENDATION"], "entities": [{"type": "movie", "value": "Interstellar"}], "confidence": 90}
- "where can i download inception" → {"primary_intent": "DOWNLOAD", "secondary_intents": ["ILLEGAL_DOWNLOAD_REQUEST"], "entities": [{"type": "movie", "value": "Inception"}], "confidence": 95}
- "legal download for avatar" → {"primary_intent": "LEGAL_DOWNLOAD", "secondary_intents": ["DOWNLOAD"], "entities": [{"type": "movie", "value": "Avatar"}], "confidence": 95}
- "trending tamil movies", "what are the current trending films" → {"primary_intent": "TRENDING", "secondary_intents": [], "entities": [{"type": "language", "value": "tamil"}], "confidence": 95}
- "top rated english films" → {"primary_intent": "TOP_RATED", "secondary_intents": [], "entities": [{"type": "language", "value": "english"}], "confidence": 95}
- "upcoming releases 2026", "new movies coming out soon" → {"primary_intent": "UPCOMING", "secondary_intents": [], "entities": [{"type": "year", "value": "2026"}], "confidence": 95}
- "what's new on netflix" → {"primary_intent": "STREAMING_DISCOVERY", "secondary_intents": [], "entities": [{"type": "platform", "value": "netflix"}], "confidence": 95}
- "oscar nominations 2026", "what awards did hitman win" → {"primary_intent": "AWARD_LOOKUP", "secondary_intents": [], "entities": [{"type": "year", "value": "2026"}], "confidence": 95}
- "explain the plot of Inception" → {"primary_intent": "PLOT_EXPLANATION", "secondary_intents": [], "entities": [{"type": "movie", "value": "Inception"}], "confidence": 95}
- "what do critics say about The Dark Knight" → {"primary_intent": "CRITIC_SUMMARY", "secondary_intents": ["REVIEWS"], "entities": [{"type": "movie", "value": "The Dark Knight"}], "confidence": 95}
- "stanley kubrick filmography", "movies directed by Scorsese" → {"primary_intent": "FILMOGRAPHY", "secondary_intents": [], "entities": [{"type": "person", "value": "Stanley Kubrick"}], "confidence": 95}
- "compare Inception and Interstellar" → {"primary_intent": "COMPARISON", "secondary_intents": [], "entities": [{"type": "movie", "value": "Inception"}, {"type": "movie", "value": "Interstellar"}], "confidence": 95}
- "analyze Antonioni's visual style" → {"primary_intent": "FILM_ANALYSIS", "secondary_intents": [], "entities": [{"type": "person", "value": "Antonioni"}], "confidence": 90}
- "suggest good thriller movies released past 2 weeks" → {"primary_intent": "RECOMMENDATION", "secondary_intents": [], "entities": [{"type": "genre", "value": "thriller"}], "confidence": 90}
- "Which movie do you think is great: 2001 or Interstellar?" → {"primary_intent": "COMPARISON", "secondary_intents": ["FILM_ANALYSIS", "CRITIC_SUMMARY", "PLOT_EXPLANATION"], "entities": [{"type": "movie", "value": "2001: A Space Odyssey"}, {"type": "movie", "value": "Interstellar"}], "confidence": 95}
- "hello", "what's up", "who are you" → {"primary_intent": "GENERAL_CONVERSATION", "secondary_intents": [], "entities": [], "confidence": 100}
- "is cgi ruining films" → {"primary_intent": "FILM_ANALYSIS", "secondary_intents": ["GENERAL_CONVERSATION"], "entities": [], "confidence": 80}

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
        if confidence < 50 and primary not in ("GREETING", "GENERAL_CONVERSATION"):
            confidence = 50

        return {
            "primary_intent": primary,
            "secondary_intents": secondary,
            "entities": entities,
            "confidence": confidence,
        }
