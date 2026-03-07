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
    def __init__(self) -> None:
        self.api_key = settings.GROQ_API_KEY
        self.model = settings.GROQ_MODEL
        if self.api_key and groq_client_type is not None:
            self.client = groq_client_type(api_key=self.api_key)
        else:
            self.client = None
        self.last_planner_raw: str = ""
        self.last_intent_raw: str = ""

    def _chat(self, messages: list[dict[str, str]], temperature: float) -> str:
        if not self.client:
            return ""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=cast(Any, messages),
                temperature=temperature,
                timeout=30.0,
            )
            return response.choices[0].message.content or ""
        except Exception:
            logging.exception("Groq request failed")
            return ""

    def propose_tools(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        content = self._chat(messages, temperature=0.2)
        self.last_planner_raw = content
        logging.getLogger(__name__).debug("Planner raw response: %s", content)
        return self._parse_planner_response(content)

    def intent_classify(self, system_prompt: str, user_prompt: str) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        content = self._chat(messages, temperature=0.2)
        self.last_intent_raw = content
        return content

    def generate_response(self, prompt: str) -> str:
        messages = [{"role": "user", "content": prompt}]
        return self._chat(messages, temperature=0.4)

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
