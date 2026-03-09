import json
import logging
from typing import Any

from google import genai
from google.genai import types
from app.config import settings


class GeminiClient:
    def __init__(self) -> None:
        self.api_key = settings.GEMINI_API_KEY
        self.model_name = settings.GEMINI_MODEL
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
        else:
            self.client = None
        self.last_planner_raw: str = ""
        self.last_intent_raw: str = ""

    def _generate(self, prompt: str, temperature: float = 0.4) -> str:
        if not self.client:
            return ""
        try:
            # New SDK uses contents for prompts
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                )
            )
            # Response.text handles concatenated parts automatically
            return response.text
        except Exception:
            logging.exception("Gemini request failed")
            return ""

    def propose_tools(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        prompt = f"{system_prompt}\n\nUser: {user_prompt}"
        content = self._generate(prompt, temperature=0.2)
        self.last_planner_raw = content
        logging.getLogger(__name__).debug("Planner raw response: %s", content)
        return self._parse_planner_response(content)

    def intent_classify(self, system_prompt: str, user_prompt: str) -> str:
        prompt = f"{system_prompt}\n\nUser: {user_prompt}"
        content = self._generate(prompt, temperature=0.2)
        self.last_intent_raw = content
        return content

    def generate_response(self, prompt: str) -> str:
        return self._generate(prompt, temperature=0.4)

    def _parse_planner_response(self, content: str) -> dict[str, Any]:
        if not content:
            return {"tools_required": [], "confidence": 100, "reasoning": ""}
        
        # Clean up possible markdown code blocks
        json_str = content
        if "```json" in content:
            json_str = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
             json_str = content.split("```")[1].split("```")[0].strip()

        try:
            data = json.loads(json_str)
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
        return {"tools_required": [], "confidence": 100, "reasoning": ""}
