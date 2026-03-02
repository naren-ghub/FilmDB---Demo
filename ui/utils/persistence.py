"""
FilmDB – Local Persistence Layer
==================================
Stores user credentials and profile data in a local JSON file
so that login/personalization survives page refreshes and restarts.
Also tracks the last active user for auto-login on refresh.
"""

import json
import hashlib
import os
from typing import Any, Dict, Optional

_DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".filmdb_users.json")


def _load_db() -> Dict[str, Any]:
    """Load the local users database."""
    if not os.path.exists(_DATA_FILE):
        return {"users": {}, "last_active_user": None}
    try:
        with open(_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "last_active_user" not in data:
                data["last_active_user"] = None
            return data
    except (json.JSONDecodeError, OSError):
        return {"users": {}, "last_active_user": None}


def _save_db(db: Dict[str, Any]) -> None:
    """Write the database to disk."""
    with open(_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


def _hash_password(password: str) -> str:
    """Simple SHA-256 hash for password storage."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


# ──────────────────────  PUBLIC API  ──────────────────────

def user_exists(username: str) -> bool:
    db = _load_db()
    return username.lower() in db["users"]


def register_user(username: str, password: str) -> bool:
    db = _load_db()
    key = username.lower()
    if key in db["users"]:
        return False
    db["users"][key] = {
        "username": username,
        "password_hash": _hash_password(password),
        "profile": None,
    }
    db["last_active_user"] = key
    _save_db(db)
    return True


def authenticate(username: str, password: str) -> bool:
    db = _load_db()
    user = db["users"].get(username.lower())
    if not user:
        return False
    return user["password_hash"] == _hash_password(password)


def set_last_active_user(username: str) -> None:
    """Mark this user as the last active (for auto-login on refresh)."""
    db = _load_db()
    db["last_active_user"] = username.lower()
    _save_db(db)


def get_last_active_user() -> Optional[Dict[str, Any]]:
    """Return the last active user's data, or None."""
    db = _load_db()
    key = db.get("last_active_user")
    if key and key in db["users"]:
        return db["users"][key]
    return None


def clear_last_active_user() -> None:
    """Clear the auto-login user (on logout)."""
    db = _load_db()
    db["last_active_user"] = None
    _save_db(db)


def save_profile(username: str, profile: Dict[str, Any]) -> None:
    db = _load_db()
    key = username.lower()
    if key in db["users"]:
        db["users"][key]["profile"] = profile
        _save_db(db)


def get_profile(username: str) -> Optional[Dict[str, Any]]:
    db = _load_db()
    user = db["users"].get(username.lower())
    if user:
        return user.get("profile")
    return None


def has_profile(username: str) -> bool:
    return get_profile(username) is not None


def delete_user(username: str) -> None:
    db = _load_db()
    key = username.lower()
    if db.get("last_active_user") == key:
        db["last_active_user"] = None
    db["users"].pop(key, None)
    _save_db(db)


def get_all_usernames() -> list:
    db = _load_db()
    return [u["username"] for u in db["users"].values()]
