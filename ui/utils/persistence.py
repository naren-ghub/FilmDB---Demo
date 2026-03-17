"""
FilmDB – Persistence Layer (SQLite)
=====================================
Thin adapter that routes all user/profile/session data to FilmDB_Demo.db
via the backend's SQLAlchemy session_store. Replaces the flat .filmdb_users.json.

The frontend (Streamlit) imports only from this module — the underlying
storage engine can be swapped without touching auth.py or chat.py.
"""

import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Make the backend app importable from the ui process
_BACKEND = Path(__file__).resolve().parent.parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.db import session_store as store
from app.db.models import SessionLocal

# Force refresh/check for required names
if not hasattr(store, "soft_delete_session_db"):
    # This might happen if uvicorn/streamlit cache is stale
    import importlib
    importlib.reload(store)

from app.db.session_store import (
    authenticate_user,
    get_chat_sessions_db,
    get_profile_db,
    register_user,
    save_chat_sessions_db,
    save_profile_db,
    user_exists_db,
    soft_delete_session_db,
    restore_session_db,
    get_deleted_chat_sessions_db,
    hard_delete_expired_sessions_db,
)


def _db():
    return SessionLocal()


# ─── Public API (same interface as the old JSON-based module) ────────────────

def user_exists(username: str) -> bool:
    db = _db()
    try:
        return user_exists_db(db, username)
    finally:
        db.close()


def register_user_ui(username: str, password: str) -> bool:
    """Create a new user. Returns True on success, False if username taken."""
    db = _db()
    try:
        return register_user(db, username, password) is not None
    finally:
        db.close()


def authenticate(username: str, password: str) -> bool:
    db = _db()
    try:
        return authenticate_user(db, username, password) is not None
    finally:
        db.close()


def save_profile(username: str, profile: Dict[str, Any]) -> None:
    db = _db()
    try:
        save_profile_db(db, username, profile)
    finally:
        db.close()


def get_profile(username: str) -> Optional[Dict[str, Any]]:
    db = _db()
    try:
        return get_profile_db(db, username)
    finally:
        db.close()


def has_profile(username: str) -> bool:
    return get_profile(username) is not None


def save_chat_sessions(username: str, sessions: dict) -> None:
    db = _db()
    try:
        save_chat_sessions_db(db, username, sessions)
    finally:
        db.close()


def get_chat_sessions(username: str) -> dict:
    db = _db()
    try:
        return get_chat_sessions_db(db, username)
    finally:
        db.close()


def soft_delete_session(session_id: str) -> bool:
    db = _db()
    try:
        return soft_delete_session_db(db, session_id)
    finally:
        db.close()


def restore_session(session_id: str) -> bool:
    db = _db()
    try:
        return restore_session_db(db, session_id)
    finally:
        db.close()


def get_deleted_chat_sessions(username: str) -> dict:
    db = _db()
    try:
        return get_deleted_chat_sessions_db(db, username)
    finally:
        db.close()


def cleanup_expired_sessions() -> int:
    db = _db()
    try:
        return hard_delete_expired_sessions_db(db)
    finally:
        db.close()


import json
import os

_LAST_USER_FILE = Path(__file__).resolve().parent.parent.parent / ".filmdb_last_user.json"

def set_last_active_user(username: str) -> None:
    """Save the last active user to a local file for auto-login on refresh."""
    try:
        profile = get_profile(username)
        data = {
            "username": username,
            "profile": profile
        }
        with open(_LAST_USER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def get_last_active_user() -> Optional[Dict[str, Any]]:
    """Retrieve the last active user for auto-login on UI refresh."""
    if _LAST_USER_FILE.exists():
        try:
            with open(_LAST_USER_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def clear_last_active_user() -> None:
    """Clear the auto-login file."""
    try:
        if _LAST_USER_FILE.exists():
            os.remove(_LAST_USER_FILE)
    except Exception:
        pass
