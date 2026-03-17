"""
FilmDB – Authentication & Onboarding
======================================
• Login tab    – authenticates against SQLite
• Register tab – creates a new account + triggers personalization
• Personalization modal – saves profile to SQLite
• Once completed, never shown again for that user
"""

import streamlit as st
from utils.persistence import (
    authenticate,
    get_chat_sessions,
    get_profile,
    has_profile,
    register_user_ui,
    save_profile,
    user_exists,
    set_last_active_user,
)


# ─────────────────────────  LOGIN / REGISTER  ─────────────────────────
def show_login_modal() -> None:
    # Hide sidebar during auth and adjust padding
    st.markdown(
        """<style>
section[data-testid='stSidebar']{display:none !important;}
.block-container{padding-top:0 !important; padding-bottom:0 !important;}
</style>""",
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:10vh;'></div>", unsafe_allow_html=True)

    _col, centre, _col2 = st.columns([1.2, 1, 1.2])
    with centre:
        st.markdown(
            """
<div class='filmdb-auth-card'>
<h2>🍿 FilmDB <span style='font-size:0.5em;color:#6c6c80;'>DEMO</span></h2>
<p class='subtitle'>Your personal cinematic intelligence</p>
</div>
            """,
            unsafe_allow_html=True,
        )

        tab_login, tab_register = st.tabs(["🔑 Login", "✨ Register"])

        # ── Login Tab ──────────────────────────────────────────────────────────
        with tab_login:
            with st.form("login_form", clear_on_submit=False):
                username = st.text_input("Username", placeholder="Enter your username", key="login_uname")
                password = st.text_input("Password", type="password", placeholder="••••••••", key="login_pw")
                submitted = st.form_submit_button("Login", use_container_width=True)

                if submitted:
                    if not username or not password:
                        st.error("Please provide both username and password.")
                    else:
                        uname = username.strip()
                        if not user_exists(uname):
                            st.error("No account found. Please register first.")
                        elif authenticate(uname, password):
                            _login_user(uname)
                        else:
                            st.error("Incorrect password. Please try again.")

        # ── Register Tab ───────────────────────────────────────────────────────
        with tab_register:
            with st.form("register_form", clear_on_submit=False):
                new_username = st.text_input("Choose a username", placeholder="e.g. cinephile_42", key="reg_uname")
                new_password = st.text_input("Choose a password", type="password", placeholder="Min. 6 characters", key="reg_pw")
                confirm_pw = st.text_input("Confirm password", type="password", placeholder="••••••••", key="reg_pw2")
                reg_submitted = st.form_submit_button("Create Account", use_container_width=True)

                if reg_submitted:
                    errors = []
                    if not new_username.strip():
                        errors.append("Username cannot be empty.")
                    elif len(new_username.strip()) < 3:
                        errors.append("Username must be at least 3 characters.")
                    if len(new_password) < 6:
                        errors.append("Password must be at least 6 characters.")
                    if new_password != confirm_pw:
                        errors.append("Passwords do not match.")
                    if errors:
                        for e in errors:
                            st.error(e)
                    elif user_exists(new_username.strip()):
                        st.error("That username is already taken. Please choose another.")
                    else:
                        ok = register_user_ui(new_username.strip(), new_password)
                        if ok:
                            st.success("Account created! Setting up your profile…")
                            _login_user(new_username.strip())
                        else:
                            st.error("Registration failed. Try a different username.")


def _login_user(username: str) -> None:
    """Set session state. Profile check triggers personalization if needed."""
    st.session_state.authenticated = True
    st.session_state.username = username
    st.session_state.user_id = username.lower()

    profile = get_profile(username)
    if profile:
        st.session_state.profile_completed = True
        st.session_state.user_profile = profile
    else:
        st.session_state.profile_completed = False

    # Restore chat sessions from SQLite
    saved_sessions = get_chat_sessions(username)
    if saved_sessions:
        st.session_state.chat_sessions = saved_sessions

    set_last_active_user(username)
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
    # Hide sidebar during profile setup
    st.markdown(
        "<style>section[data-testid='stSidebar']{display:none !important;}</style>",
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:4vh;'></div>", unsafe_allow_html=True)

    profile = st.session_state.get("user_profile", {})
    curr_region = profile.get("region", "India")
    curr_genres = [g for g in profile.get("genres", []) if g in _GENRES]
    curr_platforms = [p for p in profile.get("platforms", []) if p in _PLATFORMS]
    curr_fav_movies = ", ".join(profile.get("fav_movies", []))
    curr_fav_actors = ", ".join(profile.get("fav_actors", []))
    curr_fav_directors = ", ".join(profile.get("fav_directors", []))

    _c, centre, _c2 = st.columns([0.8, 2, 0.8])
    with centre:
        title = "Edit Your Profile" if profile else "Set Up Your Profile"
        st.markdown(
            "<div class='filmdb-profile-card'>"
            f"<h2 style='text-align:center;margin-bottom:.2rem;'>🎬 {title}</h2>"
            "<p class='subtitle' style='text-align:center;'>Tell us what you love so we can personalise your experience</p>"
            "</div>",
            unsafe_allow_html=True,
        )

        with st.form("profile_form", clear_on_submit=False):
            st.markdown("##### 🌍 Region")
            region_idx = _REGIONS.index(curr_region) if curr_region in _REGIONS else 0
            region = st.selectbox("Where are you based?", _REGIONS, index=region_idx, label_visibility="collapsed")

            st.markdown("##### 🎭 Favourite Genres")
            genres = st.multiselect(
                "Pick at least 3 genres you enjoy",
                _GENRES,
                default=curr_genres,
                label_visibility="collapsed",
            )

            st.markdown("##### 📺 Subscribed Platforms")
            platforms = st.multiselect(
                "Select the platforms you subscribe to",
                _PLATFORMS,
                default=curr_platforms,
                label_visibility="collapsed",
            )

            st.markdown("##### ⭐ Favourites")
            fav_movies = st.text_input(
                "Favourite movies (comma-separated, ≥1)",
                value=curr_fav_movies,
                placeholder="e.g. Inception, Interstellar",
            )
            fav_actors = st.text_input(
                "Favourite actors / actresses (≥1)",
                value=curr_fav_actors,
                placeholder="e.g. Keanu Reeves, Saoirse Ronan",
            )
            fav_directors = st.text_input(
                "Favourite directors (≥1)",
                value=curr_fav_directors,
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
                    save_profile(st.session_state.username, profile)
                    st.session_state.profile_completed = True
                    st.session_state.user_profile = profile
                    st.rerun()
