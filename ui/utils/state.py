"""
FilmDB – Session‑State Manager
===============================
Centralises every piece of state the app cares about so that
individual components never have to guess whether a key exists.
"""

import uuid
import streamlit as st
from utils.persistence import save_chat_sessions, get_chat_sessions


def init_session_state() -> None:
    """Idempotent – call at the very top of every run."""
    _defaults = {
        # ── auth ──
        "authenticated": False,
        "profile_completed": False,
        "user_id": None,
        "username": None,

        # ── profile ──
        "user_profile": {},

        # ── chat ──
        "session_id": str(uuid.uuid4()),
        "messages": [],            # list[dict]
        "processing": False,       # flag while awaiting backend

        # ── chat history ──
        "chat_sessions": {},       # {session_id: {"title": str, "messages": list}}

        # ── theme ──
        "theme": "dark",

        # ── chat history search ──
        "history_search": "",
    }
    for key, value in _defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def new_chat_session() -> None:
    """Archive the current chat and start a fresh session."""
    if st.session_state.messages:
        sid = st.session_state.session_id
        first_msg = st.session_state.messages[0].get("content", "Untitled")
        title = first_msg[:48] + ("…" if len(first_msg) > 48 else "")
        st.session_state.chat_sessions[sid] = {
            "title": title,
            "messages": list(st.session_state.messages),
        }
        # Persist to disk immediately so history survives refresh
        _persist_sessions()
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.messages = []
    st.session_state.processing = False


def restore_chat_session(sid: str) -> None:
    """Load a previously archived session back into the active chat."""
    session = st.session_state.chat_sessions.get(sid)
    if session:
        # Archive current first
        if st.session_state.messages:
            cur = st.session_state.session_id
            first_msg = st.session_state.messages[0].get("content", "Untitled")
            title = first_msg[:48] + ("…" if len(first_msg) > 48 else "")
            st.session_state.chat_sessions[cur] = {
                "title": title,
                "messages": list(st.session_state.messages),
            }
        st.session_state.session_id = sid
        st.session_state.messages = list(session["messages"])
        st.session_state.processing = False
        _persist_sessions()


def delete_chat_session(sid: str) -> None:
    """Remove a chat session from history."""
    st.session_state.chat_sessions.pop(sid, None)
    _persist_sessions()
    if st.session_state.session_id == sid:
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.processing = False


def rename_chat_session(sid: str, new_title: str) -> None:
    """Rename a chat session's title."""
    session = st.session_state.chat_sessions.get(sid)
    if session and new_title.strip():
        session["title"] = new_title.strip()[:64]
        _persist_sessions()


def clear_chat_messages() -> None:
    """Clear all messages in the CURRENT session (keep the session alive)."""
    st.session_state.messages = []
    st.session_state.processing = False
    # Update the stored session if it exists in history
    sid = st.session_state.session_id
    if sid in st.session_state.chat_sessions:
        st.session_state.chat_sessions[sid]["messages"] = []
        _persist_sessions()


def _persist_sessions() -> None:
    """Save chat sessions to disk."""
    username = st.session_state.get("username")
    if username:
        save_chat_sessions(username, st.session_state.chat_sessions)
