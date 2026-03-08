"""
🍿 FilmDB
==================
Production Streamlit entry‑point.

Launch:
    streamlit run app.py
"""

import streamlit as st

# ── page config must be the very first Streamlit call ──
st.set_page_config(
    page_title="FilmDB",
    page_icon="🍿",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── local imports (after set_page_config) ──
from utils.state import init_session_state              # noqa: E402
from utils.theme import load_css                         # noqa: E402
from utils.persistence import (                          # noqa: E402
    get_last_active_user,
    get_profile,
    get_chat_sessions,
)
from components.auth import (                            # noqa: E402
    show_login_modal,
    show_personalization_modal,
)
from components.chat import (                            # noqa: E402
    render_sidebar,
    render_chat_interface,
)


def _try_auto_login() -> None:
    """
    If a user previously logged in and didn't log out,
    restore their session automatically so they skip login on refresh.
    """
    if st.session_state.authenticated:
        return  # already logged in this session

    last_user = get_last_active_user()
    if last_user:
        username = last_user["username"]
        st.session_state.authenticated = True
        st.session_state.username = username
        st.session_state.user_id = username.lower()

        profile = last_user.get("profile")
        if profile:
            st.session_state.profile_completed = True
            st.session_state.user_profile = profile
        else:
            st.session_state.profile_completed = False

        # Restore persisted chat history so sidebar shows previous sessions
        saved_sessions = get_chat_sessions(username)
        if saved_sessions:
            st.session_state.chat_sessions = saved_sessions


def main() -> None:
    init_session_state()
    load_css()

    # ── attempt auto-login from persistence ──
    _try_auto_login()

    # ── gate 1: authentication ──
    if not st.session_state.authenticated:
        show_login_modal()
        return

    # ── gate 2: first‑time profile setup ──
    if not st.session_state.profile_completed:
        show_personalization_modal()
        return

    # ── authenticated + profiled → main UI ──
    render_sidebar()
    render_chat_interface()


if __name__ == "__main__":
    main()
