import importlib
import json
import logging
from typing import Any, cast

from app.config import settings


def _load_groq_class() -> Any | None:
    try:
        groq_module = importlib.import_module("groq")
        return getattr(groq_module, "Groq", None)
    except Exception:  # pragma: no cover
        return None


groq_client_type: Any | None = _load_groq_class()


class GroqClient:
    def __init__(self, api_key: str = None) -> None:
        self.api_key = api_key or settings.GROQ_API_KEY
        self.model = settings.GROQ_MODEL
        if self.api_key and groq_client_type is not None:
            self.client = groq_client_type(api_key=self.api_key)
        else:
            self.client = None
        self.last_planner_raw: str = ""
        self.last_intent_raw: str = ""
        self.total_calls: int = 0
        self.last_usage: Any | None = None

    @staticmethod
    def _strip_think_tags(text: str) -> str:
        """Strip Qwen3-style <think>...</think> reasoning blocks from output.
        Handles both closed and unclosed (cut-off) think blocks.
        """
        import re
        # First, strip fully closed blocks
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        # Then, strip any remaining unclosed <think> blocks (to handle cut-offs)
        text = re.sub(r"<think>.*", "", text, flags=re.DOTALL)
        return text.strip()

    @staticmethod
    def _extract_think_tags(text: str) -> str:
        """Extract Qwen3 <think> reasoning content for trace logging.
        Handles both closed and unclosed blocks.
        """
        import re
        # Try finding closed blocks first
        matches = re.findall(r"<think>(.*?)</think>", text, flags=re.DOTALL)
        if not matches:
            # If no closed blocks, check for an unclosed one
            match = re.search(r"<think>(.*)", text, flags=re.DOTALL)
            if match:
                return match.group(1).strip()
        return "\n".join(m.strip() for m in matches) if matches else ""

    # ── Token budget hints per intent type ──
    # NOTE: Increased significantly (+1000) to account for Qwen's internal reasoning blocks.
    _MAX_TOKENS_BY_INTENT: dict[str, int] = {
        "GREETING": 1200,
        "GENERAL_CONVERSATION": 1000,
        "ENTITY_LOOKUP": 1600,
        "PERSON_LOOKUP": 1700,
        "FILMOGRAPHY": 2000,
        "STREAMING_AVAILABILITY": 1400,
        "RECOMMENDATION": 1700,
        "COMPARISON": 2800,
        "FILM_ANALYSIS": 2800,
        "ANALYSIS_TEXT": 2800,
        "CONCEPTUAL_EXPLANATION": 2500,
        "THEORETICAL_ANALYSIS": 2500,
        "MOVEMENT_OVERVIEW": 2500,
        "VISUAL_ANALYSIS": 2400,
        "HISTORICAL_CONTEXT": 2400,
        "DIRECTOR_ANALYSIS": 2400,
        "CRITIC_REVIEW": 1800,
        "PLOT_EXPLANATION": 1700,
        "AWARD_LOOKUP": 2000,
        "TOP_RATED": 1600,
        "TRENDING": 1600,
        "DOWNLOAD": 1300,
    }

    # ── Temperature hints per intent type ──
    _TEMP_BY_INTENT: dict[str, float] = {
        "GREETING": 0.6,
        "GENERAL_CONVERSATION": 0.5,
        "ENTITY_LOOKUP": 0.3,
        "PERSON_LOOKUP": 0.3,
        "STREAMING_AVAILABILITY": 0.2,
        "RECOMMENDATION": 0.5,
        "FILM_ANALYSIS": 0.5,
        "COMPARISON": 0.5,
        "AWARD_LOOKUP": 0.2,
        "TOP_RATED": 0.3,
        "TRENDING": 0.3,
    }

    def _chat(self, messages: list[dict[str, str]], temperature: float,
              require_json: bool = False, max_tokens: int | None = None) -> str:
        if not self.client:
            return ""
        try:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": cast(Any, messages),
                "temperature": temperature,
                "timeout": 45.0,  # Increased timeout for verbose reasoning
            }
            key_mask = f"{self.api_key[:8]}...{self.api_key[-4:]}" if self.api_key else "NONE"
            logging.getLogger(__name__).info("Groq Request: model=%s key=%s", self.model, key_mask)
            if max_tokens:
                kwargs["max_tokens"] = max_tokens
            if require_json:
                kwargs["response_format"] = {"type": "json_object"}

            response = self.client.chat.completions.create(**kwargs)
            self.total_calls += 1
            content = response.choices[0].message.content or ""
            
            # Phase 10: Capture usage metrics
            self.last_usage = getattr(response, "usage", None)

            # Log reasoning traces (non-blocking)
            think_content = self._extract_think_tags(content)
            if think_content:
                logging.getLogger(__name__).debug("Qwen3 reasoning trace: %s", think_content[:500])
            self.last_think_trace = think_content

            return self._strip_think_tags(content)
        except Exception as exc:
            logging.exception("Groq request failed: %s", exc)
            self.last_usage = None
            return ""

    def propose_tools(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": system_prompt + "\nIMPORTANT: Return valid JSON only."},
            {"role": "user", "content": user_prompt},
        ]
        content = self._chat(messages, temperature=0.2, require_json=True)
        self.last_planner_raw = content
        logging.getLogger(__name__).debug("Planner raw response: %s", content)
        return self._parse_planner_response(content)

    def intent_classify(self, system_prompt: str, user_prompt: str) -> str:
        messages = [
            {"role": "system", "content": system_prompt + "\nIMPORTANT: Return valid JSON only."},
            {"role": "user", "content": user_prompt},
        ]
        content = self._chat(messages, temperature=0.2, require_json=True)
        self.last_intent_raw = content
        return content

    # ── Persona Mapping per Domain (Fixed 'Manipulation' request) ──
    _PERSONAS: dict[str, str] = {
        "film_theory": "Adopt the persona of a rigorous Film Theorist. Use scholarly terminology (e.g., formalist, semiotics, dialectics) and explore ideological subtexts with academic depth.",
        "film_criticism": "Adopt the persona of an Ebert-esque Film Critic. Balance technical appreciation with visceral emotional impact. Lead with a punchy, subjective verdict.",
        "film_history": "Adopt the persona of a Cinema Historian. Focus on lineage, influences, and the socio-political climate of the era. Connect the subject to broader historical movements.",
        "film_aesthetics": "Adopt the persona of a Visual Director of Photography. Focus intensely on lighting, composition, color science, and the formal use of space.",
        "film_production": "Adopt the persona of a seasoned Film Producer / Showrunner. Focus on the craft, structural beats, screenplay mechanics, and industry pragmatism.",
        "structured_data": "Adopt the persona of a Cinematic Librarian. Be precise, factual, and incredibly organized while maintaining an encouraging tone for discovery.",
    }

    def generate_response(self, system: str = "", user: str = "",
                          context: list[dict[str, str]] | None = None,
                          intent: str = "", domain: str = "", prompt: str = "") -> str:
        """Generate a natural-language response with proper role separation and persona injection.

        New signature (preferred):
            generate_response(system=..., user=..., context=[...], intent=..., domain=...)
        """
        # Legacy fallback
        if prompt and not system:
            system = prompt
            user = ""

        # Dynamic Persona Injection (Fixed 'Manipulation' request)
        persona_instr = self._PERSONAS.get(domain, "")
        if persona_instr:
            system = f"{system}\n\nPERSONA: {persona_instr}"

        temperature = self._TEMP_BY_INTENT.get(intent, 0.4)
        max_tokens = self._MAX_TOKENS_BY_INTENT.get(intent)

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        if context:
            messages.extend(context)
        if user:
            messages.append({"role": "user", "content": user})

        return self._chat(messages, temperature=temperature,
                          require_json=False, max_tokens=max_tokens)

    def _parse_planner_response(self, content: str) -> dict[str, Any]:
        if not content:
            return {"tools_required": [], "confidence": 100, "reasoning": ""}
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return {"tools_required": [], "confidence": 100, "reasoning": ""}
        if isinstance(data, dict) and "tools_required" in data:
            tools_required = data.get("tools_required", [])
            if not isinstance(tools_required, list):
                tools_required = []
            confidence = data.get("confidence", 100)
            if not isinstance(confidence, int):
                confidence = 100
            reasoning = data.get("reasoning", "")
            if not isinstance(reasoning, str):
                reasoning = ""
            return {
                "tools_required": tools_required,
                "confidence": confidence,
                "reasoning": reasoning,
            }
        if isinstance(data, dict) and "tool_calls" in data:
            tool_calls = data.get("tool_calls", [])
            return {
                "tools_required": tool_calls if isinstance(tool_calls, list) else [],
                "confidence": 100,
                "reasoning": "",
            }
        if isinstance(data, dict) and "tool_call" in data:
            tool_call = data.get("tool_call")
            return {
                "tools_required": [tool_call] if isinstance(tool_call, dict) else [],
                "confidence": 100,
                "reasoning": "",
            }
        return {"tools_required": [], "confidence": 100, "reasoning": ""}

