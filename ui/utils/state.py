"""
FilmDB – Session‑State Manager
===============================
Centralises every piece of state the app cares about so that
individual components never have to guess whether a key exists.
"""

import uuid
import streamlit as st


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


def delete_chat_session(sid: str) -> None:
    """Remove a chat session from history."""
    st.session_state.chat_sessions.pop(sid, None)
    if st.session_state.session_id == sid:
        new_chat_session()
