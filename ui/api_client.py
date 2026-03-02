"""
FilmDB – API Client
====================
Synchronous HTTP client for the FastAPI backend.
Handles graceful error messages so the UI never crashes.
"""

import requests
from typing import Dict, Any

API_BASE = "http://127.0.0.1:8000"
TIMEOUT  = 120  # seconds


def send_chat_message(
    session_id: str,
    user_id: str,
    message: str,
) -> Dict[str, Any]:
    """Post a chat message to the backend and return the structured response."""
    try:
        resp = requests.post(
            f"{API_BASE}/chat",
            json={
                "session_id": session_id,
                "user_id": user_id,
                "message": message,
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        return _error(
            "Unable to reach the FilmDB engine. "
            "Please ensure the backend server is running on port 8000."
        )
    except requests.exceptions.Timeout:
        return _error(
            "The request timed out. The backend may be under heavy load — please try again."
        )
    except Exception as exc:   # noqa: BLE001
        return _error(f"Unexpected error: {exc}")


def _error(text: str) -> Dict[str, Any]:
    return {
        "response_mode": "CLARIFICATION",
        "text_response": text,
        "poster_url": "",
        "streaming": [],
        "recommendations": [],
        "download_link": "",
        "sources": [],
    }
