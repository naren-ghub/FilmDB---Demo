"""
FilmDB – Chat Interface & Sidebar
===================================
Production-grade ChatGPT-like chat with:
• Deterministic response_mode rendering (FULL_CARD, RECOMMENDATION_GRID, etc.)
• Animated message bubbles with markdown support
• Enhanced Quick Actions with contextual inputs
• Sidebar with searchable chat history, feature shortcuts, and profile section
• Kebab menu for chat management (rename, clear, delete)
• Starter prompt cards for empty sessions
"""

import random
import streamlit as st
from utils.state import (
    new_chat_session,
    restore_chat_session,
    delete_chat_session,
    rename_chat_session,
    clear_chat_messages,
)
from utils.markdown_renderer import md_to_html
from utils.persistence import clear_last_active_user
from api_client import send_chat_message


# ═══════════════════════════════════════════════════════════════
#  HELPER – user profile data
# ═══════════════════════════════════════════════════════════════

def _get_region() -> str:
    return st.session_state.get("user_profile", {}).get("region", "India")


def _get_platforms() -> list:
    return st.session_state.get("user_profile", {}).get("platforms", [])


def _get_genres() -> list:
    return st.session_state.get("user_profile", {}).get("genres", [])


# ═══════════════════════════════════════════════════════════════
#  SIDEBAR
# ═══════════════════════════════════════════════════════════════

def render_sidebar() -> None:
    with st.sidebar:
        # ── branding ──
        st.markdown(
            "<div style='text-align:center;margin-bottom:0.5rem;'>"
            "<span style='font-size:1.4rem;font-weight:800;letter-spacing:-0.02em;'>"
            "🍿 <span style='color:#c9a227;'>Film</span>DB"
            "<span style='color:#6c6c80;font-size:0.7rem;margin-left:6px;'>DEMO</span>"
            "</span></div>",
            unsafe_allow_html=True,
        )

        # ── new chat ──
        st.markdown("<div class='new-chat-btn'>", unsafe_allow_html=True)
        if st.button("＋  New Chat", key="btn_new_chat", use_container_width=True):
            new_chat_session()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

        # ── chat history (always visible) ──
        _render_chat_history()

        st.markdown("---")

        # ── quick actions ──
        st.markdown(
            "<p style='font-size:0.72rem;text-transform:uppercase;"
            "letter-spacing:0.08em;color:#6c6c80;font-weight:600;"
            "margin-bottom:0.3rem;'>Quick Actions</p>",
            unsafe_allow_html=True,
        )
        _render_quick_actions()

        st.markdown("---")

        # ── profile footer ──
        username = st.session_state.get("username", "User")
        region = _get_region()
        platforms = _get_platforms()
        platform_str = ", ".join(platforms[:3]) if platforms else "—"
        st.markdown(
            f"<div style='margin-top:1rem;'>"
            f"<span class='filmdb-profile-name'>👤 {username}</span><br>"
            f"<span class='filmdb-profile-tag'>🌍 {region}  ·  📺 {platform_str}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        if st.button("Logout", key="btn_logout"):
            clear_last_active_user()
            st.session_state.clear()
            st.rerun()


# ═══════════════════════════════════════════════════════════════
#  CHAT HISTORY (always visible, searchable, editable titles)
# ═══════════════════════════════════════════════════════════════

def _render_chat_history() -> None:
    """Render the full chat history section in the sidebar with search."""
    sessions = st.session_state.get("chat_sessions", {})

    # Also ensure current session with messages is counted
    current_has_messages = bool(st.session_state.messages)

    st.markdown(
        "<p style='font-size:0.72rem;text-transform:uppercase;"
        "letter-spacing:0.08em;color:#6c6c80;font-weight:600;"
        "margin:0.6rem 0 0.3rem;'>Chat History</p>",
        unsafe_allow_html=True,
    )

    if not sessions and not current_has_messages:
        st.markdown(
            "<p style='font-size:0.8rem;color:#6c6c80;font-style:italic;"
            "margin:0.3rem 0;'>No conversations yet</p>",
            unsafe_allow_html=True,
        )
        return

    # ── search box ──
    search_query = st.text_input(
        "🔍 Search chats",
        value=st.session_state.get("history_search", ""),
        key="history_search_input",
        placeholder="Search by title…",
        label_visibility="collapsed",
    )
    st.session_state.history_search = search_query

    # Build sorted list: most recent first
    all_sessions = list(sessions.items())
    all_sessions.reverse()  # newest first

    # Filter by search
    if search_query.strip():
        query_lower = search_query.strip().lower()
        all_sessions = [
            (sid, meta) for sid, meta in all_sessions
            if query_lower in meta.get("title", "").lower()
        ]

    if not all_sessions:
        st.markdown(
            "<p style='font-size:0.8rem;color:#6c6c80;font-style:italic;"
            "margin:0.3rem 0;'>No matches found</p>",
            unsafe_allow_html=True,
        )
        return

    # ── render list (scrollable container) ──
    history_container = st.container(height=450, border=False)
    with history_container:
        for sid, meta in all_sessions[:40]:
            title = meta.get("title", "Untitled")
            # Truncate title for professional look
            display_title = (title[:25] + '...') if len(title) > 28 else title
            
            msg_count = len(meta.get("messages", []))
            is_active = sid == st.session_state.session_id

            # Highlight active session
            active_style = "color:#c9a227;font-weight:600;" if is_active else ""
            indicator = "▶ " if is_active else "💬 "

            col_title, col_edit, col_del = st.columns([5, 1, 1])
            with col_title:
                if st.button(
                    f"{indicator}{display_title}",
                    key=f"hist_{sid}",
                    use_container_width=True,
                    help=f"{title} ({msg_count} messages)",
                ):
                    restore_chat_session(sid)
                    st.rerun()
            with col_edit:
                if st.button("✏️", key=f"edit_{sid}", help="Rename"):
                    st.session_state[f"renaming_{sid}"] = True
                    st.rerun()
            with col_del:
                if st.button("🗑", key=f"del_{sid}", help="Delete"):
                    delete_chat_session(sid)
                    st.rerun()

            # Inline rename form
            if st.session_state.get(f"renaming_{sid}"):
                new_title = st.text_input(
                    "New title",
                    value=title,
                    key=f"rename_input_{sid}",
                    label_visibility="collapsed",
                )
                col_save, col_cancel = st.columns(2)
                with col_save:
                    if st.button("Save", key=f"rename_save_{sid}", use_container_width=True):
                        rename_chat_session(sid, new_title)
                        st.session_state.pop(f"renaming_{sid}", None)
                        st.rerun()
                with col_cancel:
                    if st.button("Cancel", key=f"rename_cancel_{sid}", use_container_width=True):
                        st.session_state.pop(f"renaming_{sid}", None)
                        st.rerun()


# ═══════════════════════════════════════════════════════════════
#  ENHANCED QUICK ACTIONS
# ═══════════════════════════════════════════════════════════════

def _render_quick_actions() -> None:
    """
    Smart quick actions that collect user input where needed
    and construct context-rich messages for the backend.
    """
    region = _get_region()
    platforms = _get_platforms()
    genres = _get_genres()

    # ────────────────── 1. Streaming Availability ──────────────────
    with st.expander("📺  Streaming Availability", expanded=False):
        st.caption("Check where a movie is available to stream")
        qa_movie = st.text_input(
            "Movie name",
            placeholder="e.g. Inception",
            key="qa_streaming_movie",
        )
        if st.button("Search", key="qa_streaming_go", use_container_width=True):
            if qa_movie.strip():
                msg = (
                    f"Where can I stream \"{qa_movie.strip()}\" "
                    f"in {region}?"
                )
                if platforms:
                    msg += f" I subscribe to {', '.join(platforms)}."
                _inject_user_message(msg)
            else:
                st.warning("Please enter a movie name.")

    # ────────────────── 2. Find Similar Films ──────────────────
    with st.expander("🎥  Find Similar Films", expanded=False):
        st.caption("Get recommendations based on a movie you love")
        qa_sim_movie = st.text_input(
            "Movie name",
            placeholder="e.g. Interstellar",
            key="qa_similar_movie",
        )
        qa_sim_genre = st.selectbox(
            "Preferred genre (optional)",
            ["Any"] + (genres if genres else [
                "Action", "Sci-Fi", "Drama", "Thriller", "Romance",
                "Comedy", "Horror", "Fantasy",
            ]),
            key="qa_similar_genre",
        )
        if st.button("Find Similar", key="qa_similar_go", use_container_width=True):
            if qa_sim_movie.strip():
                msg = f"Recommend movies similar to \"{qa_sim_movie.strip()}\""
                if qa_sim_genre != "Any":
                    msg += f" in the {qa_sim_genre} genre"
                msg += f". I'm based in {region}."
                _inject_user_message(msg)
            else:
                st.warning("Please enter a movie name.")

    # ────────────────── 3. Trending Now ──────────────────
    with st.expander("🔥  Trending Now", expanded=False):
        st.caption("See what's trending in your region")
        if st.button(
            f"🔥  Show trending movies in {region}",
            key="qa_trending_go",
            use_container_width=True,
        ):
            msg = f"What are the current trending movies in {region} in 2026?"
            _inject_user_message(msg)

    # ────────────────── 4. IMDb Top 250 ──────────────────
    with st.expander("🏆  IMDb Top 250", expanded=False):
        st.caption("Browse the IMDb top-rated movies of all time")
        if st.button(
            "🏆  Show IMDb Top 250",
            key="qa_top250_go",
            use_container_width=True,
        ):
            _inject_user_message("Show me the IMDb top 250 rated movies of all time")

    # ────────────────── 5. Upcoming Releases ──────────────────
    with st.expander("🎬  Upcoming Releases", expanded=False):
        st.caption(f"Movies releasing soon in {region}")
        if st.button(
            f"🎬  Upcoming releases in {region}",
            key="qa_upcoming_go",
            use_container_width=True,
        ):
            msg = f"What are the upcoming movie releases in {region}?"
            _inject_user_message(msg)

    # ────────────────── 6. Actor / Director Lookup ──────────────────
    with st.expander("🎭  Actor / Director Lookup", expanded=False):
        st.caption("Look up filmography & career details")
        qa_person_type = st.radio(
            "Looking for",
            ["Actor / Actress", "Director"],
            key="qa_person_type",
            horizontal=True,
        )
        qa_person_name = st.text_input(
            "Name",
            placeholder="e.g. Christopher Nolan",
            key="qa_person_name",
        )
        if st.button("Lookup", key="qa_person_go", use_container_width=True):
            if qa_person_name.strip():
                role = "actor" if qa_person_type == "Actor / Actress" else "director"
                msg = (
                    f"Tell me about the {role} {qa_person_name.strip()}. "
                    f"Include their filmography, achievements, and top films."
                )
                _inject_user_message(msg)
            else:
                st.warning("Please enter a name.")

    # ────────────────── 7. Movie Deep Dive ──────────────────
    with st.expander("🎞️  Movie Deep Dive", expanded=False):
        st.caption("Full details: cast, rating, plot, streaming & more")
        qa_deepdive = st.text_input(
            "Movie name",
            placeholder="e.g. The Dark Knight",
            key="qa_deepdive_movie",
        )
        if st.button("Deep Dive", key="qa_deepdive_go", use_container_width=True):
            if qa_deepdive.strip():
                msg = (
                    f"Give me a complete overview of \"{qa_deepdive.strip()}\": "
                    f"plot, cast, director, IMDb rating, streaming availability in {region}, "
                    f"and similar movie recommendations."
                )
                _inject_user_message(msg)
            else:
                st.warning("Please enter a movie name.")

    # ────────────────── 8. Platform Discovery ──────────────────
    platform_label = ", ".join(platforms[:3]) if platforms else "your platforms"
    with st.expander(f"📡  What's New on {platform_label}", expanded=False):
        if platforms:
            st.caption(f"Discover trending content on {', '.join(platforms)}")
        else:
            st.caption("Set up your platforms in your profile to personalise this")
        if st.button(
            f"📡  Show me what's new",
            key="qa_platform_go",
            use_container_width=True,
        ):
            if platforms:
                msg = (
                    f"What are the latest and most popular movies currently available on "
                    f"{', '.join(platforms)} in {region}?"
                )
            else:
                msg = f"What are the latest and most popular movies streaming in {region}?"
            _inject_user_message(msg)


# ═══════════════════════════════════════════════════════════════
#  MAIN CHAT INTERFACE
# ═══════════════════════════════════════════════════════════════

def render_chat_interface() -> None:
    # ── title bar with kebab menu ──
    title_col, menu_col = st.columns([6, 1])
    with title_col:
        st.markdown(
            "<div class='filmdb-title'>🍿 <span>Film</span>DB "
            "<span style='font-size:0.55em;color:#6c6c80;'></span></div>",
            unsafe_allow_html=True,
        )
    with menu_col:
        _render_kebab_menu()

    # ── starter cards (only when chat is empty) ──
    if not st.session_state.messages:
        _render_starter_cards()

    # ── message history ──
    for msg in st.session_state.messages:
        if msg.get("role") == "user":
            _render_user_bubble(msg["content"])
        else:
            _render_assistant_response(msg)

    # ── process pending request ──
    if st.session_state.get("processing"):
        _process_pending_message()

    # ── chat input (pinned at bottom by Streamlit) ──
    prompt = st.chat_input("Ask FilmDB about movies, actors, or streaming…")
    if prompt:
        _inject_user_message(prompt)


# ═══════════════════════════════════════════════════════════════
#  KEBAB MENU (three-dot chat management)
# ═══════════════════════════════════════════════════════════════

def _render_kebab_menu() -> None:
    """Three-dot kebab menu for rename, clear, delete actions on current chat."""
    sessions = st.session_state.get("chat_sessions", {})
    current_sid = st.session_state.session_id
    current_title = ""
    if current_sid in sessions:
        current_title = sessions[current_sid].get("title", "")

    with st.popover("⋮", help="Chat options"):
        st.markdown(
            "<p style='font-size:0.75rem;color:#6c6c80;text-transform:uppercase;"
            "letter-spacing:0.06em;font-weight:600;margin-bottom:0.5rem;'>Chat Options</p>",
            unsafe_allow_html=True,
        )

        # ── Rename ──
        if st.session_state.get("kebab_renaming"):
            new_name = st.text_input(
                "New title",
                value=current_title,
                key="kebab_rename_input",
                label_visibility="collapsed",
            )
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✓ Save", key="kebab_rename_save", use_container_width=True):
                    if new_name.strip():
                        # If current session isn't archived yet, archive it first
                        if current_sid not in sessions and st.session_state.messages:
                            first_msg = st.session_state.messages[0].get("content", "Untitled")
                            sessions[current_sid] = {
                                "title": new_name.strip()[:64],
                                "messages": list(st.session_state.messages),
                            }
                            st.session_state.chat_sessions = sessions
                        rename_chat_session(current_sid, new_name)
                    st.session_state.pop("kebab_renaming", None)
                    st.rerun()
            with c2:
                if st.button("✕ Cancel", key="kebab_rename_cancel", use_container_width=True):
                    st.session_state.pop("kebab_renaming", None)
                    st.rerun()
        else:
            if st.button("✏️  Rename Chat", key="kebab_rename_btn", use_container_width=True):
                st.session_state["kebab_renaming"] = True
                st.rerun()

        # ── Clear Chat ──
        if st.button("🧹  Clear Chat", key="kebab_clear_btn", use_container_width=True,
                      help="Clears all messages but keeps the session"):
            clear_chat_messages()
            st.rerun()

        # ── Delete Chat ──
        if st.button("🗑️  Delete Chat", key="kebab_delete_btn", use_container_width=True,
                      help="Permanently removes this chat"):
            if current_sid in sessions:
                delete_chat_session(current_sid)
            else:
                st.session_state.messages = []
                st.session_state.session_id = __import__("uuid").uuid4().__str__()
            st.rerun()


# ═══════════════════════════════════════════════════════════════
#  STARTER PROMPT CARDS
# ═══════════════════════════════════════════════════════════════

def _render_starter_cards() -> None:
    """Dynamic welcome area — suggestions rotate per session and adapt to user profile + history."""
    region = _get_region()
    platforms = _get_platforms()
    genres = _get_genres()
    profile = st.session_state.get("user_profile", {})
    fav_movies = profile.get("fav_movies", [])
    fav_actors = profile.get("fav_actors", [])
    fav_directors = profile.get("fav_directors", [])
    platform_str = ", ".join(platforms[:2]) if platforms else "streaming platforms"

    # ── Build a pool of personalised suggestions ──
    pool = []

    # Profile-based
    for movie in fav_movies[:3]:
        pool.append(f"🎬 &nbsp; <i>Movies similar to {movie}</i>")
        pool.append(f"📺 &nbsp; <i>Where can I stream {movie}?</i>")
    for actor in fav_actors[:3]:
        pool.append(f"🎭 &nbsp; <i>Tell me about {actor}</i>")
        pool.append(f"🎥 &nbsp; <i>Best movies by {actor}</i>")
    for director in fav_directors[:3]:
        pool.append(f"🎬 &nbsp; <i>{director}'s filmography</i>")
        pool.append(f"🏆 &nbsp; <i>Awards won by {director}</i>")
    for genre in genres[:4]:
        pool.append(f"🔥 &nbsp; <i>Best {genre} movies of all time</i>")

    # History-based: extract topics from past sessions
    sessions = st.session_state.get("chat_sessions", {})
    for _sid, meta in list(sessions.items())[:5]:
        title = meta.get("title", "")
        if title and len(title) > 5:
            pool.append(f"💬 &nbsp; <i>{title}</i>")

    # Generic fallbacks (always available)
    generic = [
        f"🔥 &nbsp; <i>What's trending in {region}?</i>",
        "🏆 &nbsp; <i>Top 250 IMDb movies of all time</i>",
        f"📺 &nbsp; <i>What's new on {platform_str}?</i>",
        f"🎬 &nbsp; <i>Upcoming movie releases in {region}</i>",
        "🎭 &nbsp; <i>Who is the highest-paid actor in 2026?</i>",
        "📰 &nbsp; <i>Latest Oscar nominations</i>",
        "🎞️ &nbsp; <i>Most anticipated films this year</i>",
    ]
    pool.extend(generic)

    # ── Pick 4 unique suggestions, seeded by session_id for consistency within a session ──
    session_seed = st.session_state.get("session_id", "default")
    rng = random.Random(session_seed)
    seen_texts = set()
    unique_pool = []
    for s in pool:
        text_key = s.lower().strip()
        if text_key not in seen_texts:
            seen_texts.add(text_key)
            unique_pool.append(s)
    suggestions = rng.sample(unique_pool, min(4, len(unique_pool)))

    st.markdown(
        "<div style='text-align:center;margin:2.5rem 0 1rem;'>"
        "<span style='font-size:2.2rem;'>🎬</span>"
        "<p style='color:#a0a0b8;font-size:0.95rem;margin-top:0.5rem;line-height:1.7;'>"
        "Ask me anything about movies, actors, or streaming.<br>"
        "Try the <b style='color:#c9a227;'>Quick Actions</b> in the sidebar, or type a question below."
        "</p></div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        "<div style='display:flex;flex-wrap:wrap;justify-content:center;gap:0.6rem;margin-bottom:1.5rem;'>"
        + "".join(
            f"<span style='background:#1a1a2e;border:1px solid rgba(255,255,255,0.06);"
            f"border-radius:20px;padding:0.45rem 1rem;font-size:0.82rem;color:#a0a0b8;'>{s}</span>"
            for s in suggestions
        )
        + "</div>",
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════
#  MESSAGE BUBBLES
# ═══════════════════════════════════════════════════════════════

def _render_user_bubble(content: str) -> None:
    safe = content.replace("<", "&lt;").replace(">", "&gt;")
    st.markdown(
        f"<div class='filmdb-user-msg'>{safe}</div>",
        unsafe_allow_html=True,
    )


def _render_assistant_response(msg: dict) -> None:
    """Deterministic rendering based on response_mode."""
    mode = msg.get("response_mode", "EXPLANATION_ONLY")
    text = msg.get("text_response", msg.get("content", ""))
    poster = msg.get("poster_url", "")
    streaming = msg.get("streaming", [])
    recommendations = msg.get("recommendations", [])
    sources = msg.get("sources", [])
    download = msg.get("download_link", "")

    # ── FULL_CARD: poster + metadata side-by-side ──
    if mode == "FULL_CARD" and poster:
        title = msg.get("title", "Unknown Title")
        director = msg.get("director", "Unknown Director")
        year = msg.get("year", "")
        rating = msg.get("rating", "N/A")
        
        platforms_str = ", ".join([s.get("name") if isinstance(s, dict) else str(s) for s in streaming]) if streaming else "Not available to stream"
        
        import textwrap
        
        hide_footer = mode in ("AVAILABILITY_FOCUS", "EXPLANATION_PLUS_AVAILABILITY") or not streaming
        footer_line = ""
        if not hide_footer:
            footer_line = f'<div style="margin-top:15px; padding-top:10px; border-top: 1px solid #333; clear: both;"><b style="color:#c9a227;">Where to Watch:</b> {platforms_str}</div>'
        
        # We use a float-based layout so text wraps around the poster.
        html = textwrap.dedent(f"""
            <div style="padding:18px; border-radius:12px; background-color:#111; border:1px solid #333; margin-bottom:20px; overflow: auto;">
                <div style="float: left; margin: 0 20px 10px 0;">
                    <img src="{poster}" style="width:200px; border-radius:8px; display: block;">
                </div>
                <div style="color: white;">
                    <h2 style="margin-bottom:5px; margin-top:0;">{title}</h2>
                    <p style="color:#bbb;margin-top:0;">{director} • {year} • ⭐ {rating}</p>
                    <div style="line-height:1.6; font-size: 0.95rem;">
                        {md_to_html(text)}
                    </div>
                    {footer_line}
                </div>
            </div>
        """).strip()
        st.markdown(html, unsafe_allow_html=True)
    else:
        # ── text bubble for all other modes ──
        st.markdown(
            f"<div class='filmdb-asst-msg'>{md_to_html(text)}</div>",
            unsafe_allow_html=True,
        )

    # ── AVAILABILITY_FOCUS / EXPLANATION_PLUS_AVAILABILITY ──
    if mode in ("AVAILABILITY_FOCUS", "EXPLANATION_PLUS_AVAILABILITY") and streaming:
        _render_platforms(streaming)

    # ── RECOMMENDATION_GRID ──
    if mode == "RECOMMENDATION_GRID" and recommendations:
        _render_recommendations(recommendations)
    elif recommendations and mode not in ("CLARIFICATION",):
        _render_recommendations(recommendations)

    # ── Download link ──
    if download:
        st.markdown(
            f"<a href='{download}' target='_blank' "
            f"style='color:#c9a227;font-weight:600;font-size:0.9rem;'>"
            f"⬇ Download from Internet Archive</a>",
            unsafe_allow_html=True,
        )

    # ── collapsible sources ──
    if sources:
        _render_sources(sources)


# ═══════════════════════════════════════════════════════════════
#  SUB‑COMPONENTS
# ═══════════════════════════════════════════════════════════════

def _render_platforms(streaming: list) -> None:
    badges_html = ""
    for s in streaming:
        name = s.get("name") if isinstance(s, dict) else str(s)
        badges_html += f"<span class='filmdb-platform-badge'>{name}</span>"
    st.markdown(
        f"<div style='margin:0.5rem 0 0.8rem;'>"
        f"<span style='font-size:0.78rem;color:#a0a0b8;font-weight:600;'>Available on</span><br>"
        f"{badges_html}</div>",
        unsafe_allow_html=True,
    )


def _render_recommendations(recs: list) -> None:
    st.markdown("### Recommended Movies")
    cols = st.columns(min(len(recs), 3), gap="small")
    for i, rec in enumerate(recs[:6]):
        with cols[i % 3]:
            if isinstance(rec, dict):
                title = rec.get("title", "Unknown")
                poster = rec.get("poster_url", "")
                st.markdown(f"<div class='filmdb-rec-card'>", unsafe_allow_html=True)
                if poster:
                    st.image(poster, use_container_width=True)
                st.markdown(
                    f"<div class='filmdb-rec-title'>{title}</div></div>",
                    unsafe_allow_html=True,
                )
                if st.button(f"Ask about {title}", key=f"rec_{i}_{title[:12]}"):
                    _inject_user_message(f"Tell me about {title}")
            else:
                st.markdown(
                    f"<div class='filmdb-rec-card'>"
                    f"<div class='filmdb-rec-title'>{rec}</div></div>",
                    unsafe_allow_html=True,
                )


def _render_sources(sources: list) -> None:
    with st.expander("📎 Sources", expanded=False):
        for src in sources:
            if isinstance(src, dict):
                url = src.get("url", src.get("link", ""))
                title = src.get("title", url)
                st.markdown(f"- [{title}]({url})")
            else:
                st.markdown(f"- [{src}]({src})")


# ═══════════════════════════════════════════════════════════════
#  INPUT HANDLING
# ═══════════════════════════════════════════════════════════════

def _inject_user_message(text: str) -> None:
    """Add a user message and flag it for backend processing."""
    st.session_state.messages.append({"role": "user", "content": text})
    st.session_state.processing = True
    st.rerun()


def _process_pending_message() -> None:
    """Send the last user message to the backend and append the response."""
    st.session_state.processing = False
    last_user_msg = ""
    for m in reversed(st.session_state.messages):
        if m.get("role") == "user":
            last_user_msg = m["content"]
            break

    if not last_user_msg:
        return

    with st.spinner("Fetching cinematic intelligence…"):
        resp = send_chat_message(
            session_id=st.session_state.session_id,
            user_id=st.session_state.user_id,
            message=last_user_msg,
        )

    resp["role"] = "assistant"
    st.session_state.messages.append(resp)

    # Auto-save current session to history after each response
    sid = st.session_state.session_id
    sessions = st.session_state.get("chat_sessions", {})
    if sid not in sessions:
        first_user_msg = next((m.get("content", "") for m in st.session_state.messages if m.get("role") == "user"), "")
        if not first_user_msg:
            title = "New Conversation"
        else:
            clean_msg = first_user_msg.strip(" ?.!\"'")
            if len(clean_msg) > 30:
                title = clean_msg[:28].rsplit(" ", 1)[0] + "…"
            else:
                title = clean_msg
            title = title.capitalize()
    else:
        title = sessions[sid].get("title", "Untitled")
    sessions[sid] = {
        "title": title,
        "messages": list(st.session_state.messages),
    }
    st.session_state.chat_sessions = sessions
    # Persist to disk
    username = st.session_state.get("username")
    if username:
        from utils.persistence import save_chat_sessions
        save_chat_sessions(username, sessions)

    st.rerun()
