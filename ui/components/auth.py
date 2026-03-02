"""
FilmDB – Authentication & Onboarding
======================================
• Login modal – authenticates against local persistence
• Personalization modal – saves profile to disk
• Once completed, never shown again for that user
"""

import streamlit as st
from utils.persistence import (
    user_exists,
    register_user,
    authenticate,
    save_profile,
    get_profile,
    has_profile,
    set_last_active_user,
)


# ─────────────────────────  LOGIN  ─────────────────────────
def show_login_modal() -> None:
    st.markdown("<div class='filmdb-auth-wrapper'>", unsafe_allow_html=True)

    _col, centre, _col2 = st.columns([1, 1.4, 1])
    with centre:
        st.markdown(
            """
            <div class='filmdb-auth-card'>
                <h2>🍿 FilmDB</h2>
                <p class='subtitle'>Your personal cinematic intelligence</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input("Password", type="password", placeholder="••••••••")
            submitted = st.form_submit_button("Continue", use_container_width=True)

            if submitted:
                if not username or not password:
                    st.error("Please provide both username and password.")
                else:
                    uname = username.strip()
                    if user_exists(uname):
                        # ── existing user: authenticate ──
                        if authenticate(uname, password):
                            _login_user(uname)
                        else:
                            st.error("Incorrect password. Please try again.")
                    else:
                        # ── new user: register ──
                        register_user(uname, password)
                        _login_user(uname)
                        st.toast(f"Welcome, {uname}! Account created.", icon="🎉")

    st.markdown("</div>", unsafe_allow_html=True)


def _login_user(username: str) -> None:
    """Set session state and skip personalization if profile already exists."""
    st.session_state.authenticated = True
    st.session_state.username = username
    st.session_state.user_id = username.lower()

    # Mark as last active for auto-login on refresh
    set_last_active_user(username)

    profile = get_profile(username)
    if profile:
        st.session_state.profile_completed = True
        st.session_state.user_profile = profile
    else:
        st.session_state.profile_completed = False

    st.rerun()


# ─────────────────────  PERSONALIZATION  ─────────────────────
_REGIONS = [
    "India", "USA", "UK", "Canada", "Australia",
    "Germany", "France", "Japan", "South Korea", "Other",
]

_GENRES = [
    "Action", "Sci-Fi", "Drama", "Thriller", "Romance",
    "Comedy", "Horror", "Fantasy", "Crime", "Adventure",
    "Animation", "Documentary",
]

_PLATFORMS = [
    "Netflix", "Prime Video", "Disney+", "Hotstar",
    "Apple TV+", "Hulu", "HBO", "Zee5", "SonyLIV", "YouTube Movies",
]


def show_personalization_modal() -> None:
    st.markdown("<div class='filmdb-auth-wrapper'>", unsafe_allow_html=True)

    _c, centre, _c2 = st.columns([1, 2.2, 1])
    with centre:
        st.markdown(
            "<div class='filmdb-profile-card'>"
            "<h2 style='text-align:center;margin-bottom:.2rem;'>🎬 Set Up Your Profile</h2>"
            "<p class='subtitle' style='text-align:center;'>Tell us what you love so we can personalise your feed</p>"
            "</div>",
            unsafe_allow_html=True,
        )

        with st.form("profile_form", clear_on_submit=False):
            st.markdown("##### 🌍 Region")
            region = st.selectbox("Where are you based?", _REGIONS, label_visibility="collapsed")

            st.markdown("##### 🎭 Favourite Genres")
            genres = st.multiselect(
                "Pick at least 3 genres you enjoy",
                _GENRES,
                label_visibility="collapsed",
            )

            st.markdown("##### 📺 Subscribed Platforms")
            platforms = st.multiselect(
                "Select the platforms you subscribe to",
                _PLATFORMS,
                label_visibility="collapsed",
            )

            st.markdown("##### ⭐ Favourites")
            fav_movies = st.text_input(
                "Favourite movies (comma-separated, ≥1)",
                placeholder="e.g. Inception, Interstellar",
            )
            fav_actors = st.text_input(
                "Favourite actors / actresses (≥1)",
                placeholder="e.g. Keanu Reeves, Saoirse Ronan",
            )
            fav_directors = st.text_input(
                "Favourite directors (≥1)",
                placeholder="e.g. Christopher Nolan, Denis Villeneuve",
            )

            submitted = st.form_submit_button("Save & Continue", use_container_width=True)

            if submitted:
                errors = []
                if len(genres) < 3:
                    errors.append("Select at least **3** genres.")
                if not fav_movies.strip():
                    errors.append("Enter at least **1** favourite movie.")
                if not fav_actors.strip():
                    errors.append("Enter at least **1** favourite actor/actress.")
                if not fav_directors.strip():
                    errors.append("Enter at least **1** favourite director.")

                if errors:
                    for e in errors:
                        st.error(e)
                else:
                    profile = {
                        "region": region,
                        "genres": genres,
                        "platforms": platforms,
                        "fav_movies": [m.strip() for m in fav_movies.split(",") if m.strip()],
                        "fav_actors": [a.strip() for a in fav_actors.split(",") if a.strip()],
                        "fav_directors": [d.strip() for d in fav_directors.split(",") if d.strip()],
                    }
                    # ── persist to disk ──
                    save_profile(st.session_state.username, profile)

                    st.session_state.profile_completed = True
                    st.session_state.user_profile = profile
                    st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)
