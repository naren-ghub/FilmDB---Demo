"""
FilmDB – Chat Interface & Sidebar
===================================
Production-grade ChatGPT-like chat with:
• Deterministic response_mode rendering (FULL_CARD, RECOMMENDATION_GRID,    A sleek chat UI component handling user input, message styling,
    and server state updates.
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

            col_title, col_edit, col_del = st.columns([6.5, 1.25, 1.25])
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
#  MAIN CHAT INTERFACE
# ═══════════════════════════════════════════════════════════════

def render_chat_interface() -> None:
    # ── title bar with kebab menu ──
    # If currently renaming the chat via the kebab menu, show inline input
    if st.session_state.get("kebab_renaming"):
        _render_inline_rename()
    else:
        title_col, menu_col = st.columns([6, 1])
        with title_col:
            st.markdown(
                "<div class='filmdb-title' style='display:flex; align-items:center; height:100%; margin:0;'>"
                "🍿&nbsp;&nbsp;<span>Film</span>DB&nbsp;"
                "<span style='font-size:0.55em;color:#6c6c80;margin-left:8px;margin-top:8px;'>DEMO</span>"
                "</div>",
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

    with st.popover("⋮", help="Chat options"):
        st.markdown(
            "<p style='font-size:0.75rem;color:#6c6c80;text-transform:uppercase;"
            "letter-spacing:0.06em;font-weight:600;margin-bottom:0.5rem;'>Chat Options</p>",
            unsafe_allow_html=True,
        )

        # ── Rename (Sets state for inline render) ──
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

def _render_inline_rename() -> None:
    """Renders the rename input field inline instead of inside the popover."""
    sessions = st.session_state.get("chat_sessions", {})
    current_sid = st.session_state.session_id
    current_title = sessions.get(current_sid, {}).get("title", "") if current_sid in sessions else ""

    col_input, col_save, col_cancel = st.columns([5, 1, 1])
    with col_input:
        new_name = st.text_input(
            "New title",
            value=current_title,
            key="kebab_rename_input_inline",
            label_visibility="collapsed",
        )
    with col_save:
        if st.button("✓ Save", key="kebab_rename_save_inline", use_container_width=True):
            if new_name.strip():
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
    with col_cancel:
        if st.button("✕ Cancel", key="kebab_rename_cancel_inline", use_container_width=True):
            st.session_state.pop("kebab_renaming", None)
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
        "Type a question below to get started."
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
    """Deterministic rendering based on response_mode and entity_type."""
    mode = msg.get("response_mode", "EXPLANATION_ONLY")
    text = msg.get("text_response", msg.get("content", ""))
    poster = msg.get("poster_url", "")
    entity_type = msg.get("entity_type", "")
    streaming = msg.get("streaming", [])
    recommendations = msg.get("recommendations", [])
    sources = msg.get("sources", [])
    download = msg.get("download_link", "")
    genres = msg.get("genres", [])
    awards = msg.get("awards", {})
    trailer_key = msg.get("trailer_key", "")

    # ── PERSON CARD ────────────────────────────────────────────────────────────
    if entity_type == "person" or mode in ("PERSON_LOOKUP", "FILMOGRAPHY"):
        _render_person_card(msg)

    # ── FULL MOVIE CARD (only for movie entities) ──────────────────────────────
    elif mode == "FULL_CARD" and poster and entity_type != "person":
        title = msg.get("title", "Unknown Title")
        director = msg.get("director", "Unknown Director")
        year = msg.get("year", "")
        rating = msg.get("rating", "")
        accent = _genre_accent(genres)
        rating_html = _rating_gauge(rating)
        badges_html = _award_badges(awards)

        html = f"""
<div style="padding:18px; border-radius:12px; background:#111;
     border:1px solid #333; border-left:4px solid {accent};
     margin-bottom:20px; overflow:auto;">
    <div style="float:left; margin:0 20px 10px 0;">
        <img src="{poster}" style="width:200px; border-radius:8px; display:block;">
    </div>
    <div style="color:white;">
        <h2 style="margin:0 0 5px;">{title}</h2>
        <p style="color:#bbb;margin:0 0 4px;">{director} &bull; {year}</p>
        {rating_html}
        {badges_html}
        <div style="line-height:1.6; font-size:0.95rem; margin-top:10px;">
            {md_to_html(text)}
        </div>
    </div>
</div>""".strip()
        st.markdown(html, unsafe_allow_html=True)

        # Trailer embed
        if trailer_key:
            st.markdown(
                f'<div style="margin-top:12px; border-radius:8px; overflow:hidden;">'
                f'<iframe width="100%" height="280" '
                f'src="https://www.youtube.com/embed/{trailer_key}?rel=0" '
                f'frameborder="0" allowfullscreen></iframe></div>',
                unsafe_allow_html=True,
            )

        # Watchlist button
        col_w, col_f, _ = st.columns([2, 2, 6])
        with col_w:
            if st.button("📌 Watchlist", key=f"wl_{title[:14]}", use_container_width=True):
                _add_to_watchlist(title, msg.get("imdb_id", ""))
        with col_f:
            if st.button("❤️ Favourite", key=f"fav_{title[:14]}", use_container_width=True):
                _add_to_watchlist(title, msg.get("imdb_id", ""), list_key="favorites")

    # ── COMPARISON LAYOUT ──────────────────────────────────────────────────────
    elif mode == "COMPARISON_TABLE":
        _render_comparison(msg)

    # ── DEFAULT TEXT BUBBLE (all other modes) ─────────────────────────────────
    else:
        _render_with_spoiler_guard(text, mode)

    # ── STREAMING PLATFORMS (only for movie entities) ─────────────────────────
    if entity_type != "person" and mode in ("AVAILABILITY_FOCUS", "EXPLANATION_PLUS_AVAILABILITY", "FULL_CARD") and streaming:
        _render_platforms(streaming)

    # ── RECOMMENDATIONS ────────────────────────────────────────────────────────
    if recommendations and mode not in ("CLARIFICATION",):
        _render_recommendations(recommendations)

    # ── DOWNLOAD CARD ──────────────────────────────────────────────────────────
    if download:
        st.markdown(f"""
<div style="background:#1a1a2e; border:1px solid rgba(201,162,39,.3);
     border-radius:12px; padding:14px 18px; margin-top:10px;
     display:flex; align-items:center; gap:12px;">
    <span style="font-size:1.8rem;">📦</span>
    <div style="flex:1;">
        <div style="font-weight:600; font-size:0.9rem; color:#eaeaea;">Public Domain Download</div>
        <div style="font-size:0.78rem; color:#6c6c80;">Internet Archive — Free &amp; Legal</div>
    </div>
    <a href="{download}" target="_blank" style="background:linear-gradient(135deg,#c9a227,#d4a017);
       color:#0d0d0d; padding:8px 16px; border-radius:8px; font-weight:600;
       font-size:0.85rem; text-decoration:none;">Download ⬇</a>
</div>""", unsafe_allow_html=True)

    # ── SOURCES ────────────────────────────────────────────────────────────────
    if sources:
        _render_sources(sources)


# ═══════════════════════════════════════════════════════════════
#  RICH CARD HELPERS
# ═══════════════════════════════════════════════════════════════

_GENRE_COLORS = {
    "Horror": "#8b0000", "Thriller": "#4a0e0e", "Sci-Fi": "#1a237e",
    "Science Fiction": "#1a237e", "Romance": "#880e4f", "Comedy": "#e65100",
    "Drama": "#3e2723", "Animation": "#1b5e20", "Documentary": "#004d40",
    "Action": "#bf360c", "Crime": "#311b92", "Fantasy": "#1a237e",
}

def _genre_accent(genres: list) -> str:
    for g in genres:
        if g in _GENRE_COLORS:
            return _GENRE_COLORS[g]
    return "#c9a227"  # default gold


def _rating_gauge(rating) -> str:
    if not rating:
        return ""
    try:
        r = float(rating)
    except (ValueError, TypeError):
        return f"<p style='color:#bbb;font-size:0.9rem;'>⭐ {rating}</p>"
    pct = (r / 10) * 100
    color = "#4caf50" if r >= 7 else "#ff9800" if r >= 5 else "#f44336"
    return f"""
<div style="display:flex; align-items:center; gap:8px; margin:6px 0;">
    <span style="font-weight:700; font-size:1.1rem; color:{color};">{r}</span>
    <div style="width:110px; height:6px; background:#1a1a2e; border-radius:3px; overflow:hidden;">
        <div style="width:{pct:.0f}%; height:100%; background:{color}; border-radius:3px;"></div>
    </div>
    <span style="font-size:0.7rem; color:#6c6c80;">/ 10 IMDb</span>
</div>"""


def _award_badges(awards: dict) -> str:
    if not awards:
        return ""
    wins = awards.get("oscar_wins", [])
    noms = awards.get("oscar_nominations", [])
    html = ""
    if wins:
        html += (f'<span style="display:inline-block; background:linear-gradient(135deg,#c9a227,#d4a017);'
                 f'color:#0d0d0d; font-size:0.75rem; font-weight:700; padding:3px 10px;'
                 f'border-radius:50px; margin:2px;">🏆 {len(wins)} Oscar Win{"s" if len(wins)>1 else ""}</span>')
    if noms:
        html += (f'<span style="display:inline-block; background:#22223a;color:#c9a227;'
                 f'font-size:0.75rem; font-weight:600; padding:3px 10px; border-radius:50px;'
                 f'border:1px solid rgba(201,162,39,.4); margin:2px;">🎬 {len(noms)} Nomination{"s" if len(noms)>1 else ""}</span>')
    return f"<div style='margin:6px 0;'>{html}</div>" if html else ""


def _render_person_card(msg: dict) -> None:
    name = msg.get("person_name") or msg.get("title") or "Unknown"
    photo = msg.get("poster_url", "")
    profession = msg.get("profession", "")
    birth = msg.get("birth_date", "")
    text = msg.get("text_response", msg.get("content", ""))
    photo_html = (f"<img src='{photo}' style='width:160px; height:160px; object-fit:cover; border-radius:50%; border:3px solid #c9a227;'>"
                  if photo else
                  "<div style='width:160px; height:160px; border-radius:50%; background:#1a1a2e; display:flex; align-items:center; justify-content:center; font-size:3rem;'>🎬</div>")
    meta = " &bull; ".join(filter(None, [profession, f"Born: {birth}" if birth else ""]))
    st.markdown(f"""
<div style="padding:18px; border-radius:12px; background:#111;
     border:1px solid #333; border-left:4px solid #c9a227;
     margin-bottom:20px; overflow:auto;">
    <div style="float:left; margin:0 20px 10px 0; text-align:center;">
        {photo_html}
    </div>
    <div style="color:white;">
        <h2 style="margin:0 0 5px; color:#c9a227;">{name}</h2>
        <p style="color:#a0a0b8; margin:0 0 10px; font-size:0.9rem;">{meta}</p>
        <div style="line-height:1.6; font-size:0.95rem;">{md_to_html(text)}</div>
    </div>
</div>""", unsafe_allow_html=True)


def _render_comparison(msg: dict) -> None:
    movie_a = {"title": msg.get("title", "Film A"), "poster_url": msg.get("poster_url", ""), "year": msg.get("year", ""), "rating": msg.get("rating", "")}
    text = msg.get("text_response", msg.get("content", ""))
    col_a, col_vs, col_b = st.columns([5, 1, 5])
    with col_a:
        _render_comparison_half(movie_a)
    with col_vs:
        st.markdown("<div style='display:flex;align-items:center;justify-content:center;height:100%;font-size:1.4rem;color:#c9a227;font-weight:800;padding-top:60px;'>VS</div>", unsafe_allow_html=True)
    with col_b:
        st.markdown("<div style='padding:12px;background:#1a1a2e;border-radius:12px;border:1px solid #333;text-align:center;color:#a0a0b8;font-size:0.85rem;'>Film B data available in next response</div>", unsafe_allow_html=True)
    _render_with_spoiler_guard(text, "COMPARISON_TABLE")


def _render_comparison_half(movie: dict) -> None:
    poster = movie.get("poster_url", "")
    title = movie.get("title", "")
    year = movie.get("year", "")
    rating = movie.get("rating", "")
    st.markdown(f"""
<div style="text-align:center; padding:12px; background:#1a1a2e;
     border-radius:12px; border:1px solid #333;">
    {'<img src="' + poster + '" style="width:150px; border-radius:8px; margin-bottom:8px;">' if poster else ''}
    <div style="font-weight:700; color:#c9a227; margin-bottom:4px;">{title}</div>
    <div style="font-size:0.85rem; color:#a0a0b8;">{year} &bull; ⭐ {rating}</div>
</div>""", unsafe_allow_html=True)


def _render_with_spoiler_guard(text: str, mode: str) -> None:
    spoiler_modes = ("PLOT_EXPLANATION", "ANALYSIS_TEXT", "CRITIC_REVIEW")
    if mode in spoiler_modes and ("**SPOILER**" in text or "[SPOILER]" in text):
        marker = "**SPOILER**" if "**SPOILER**" in text else "[SPOILER]"
        parts = text.split(marker, 1)
        st.markdown(f"<div class='filmdb-asst-msg'>{md_to_html(parts[0])}</div>", unsafe_allow_html=True)
        with st.expander("⚠️ Contains Spoilers — Click to reveal", expanded=False):
            st.markdown(md_to_html(parts[1] if len(parts) > 1 else ""), unsafe_allow_html=True)
    else:
        st.markdown(f"<div class='filmdb-asst-msg'>{md_to_html(text)}</div>", unsafe_allow_html=True)


def _add_to_watchlist(title: str, imdb_id: str, list_key: str = "watchlist") -> None:
    import datetime as dt
    profile = st.session_state.get("user_profile", {})
    lst = profile.get(list_key, [])
    entry = {"title": title, "imdb_id": imdb_id, "added_at": str(dt.date.today())}
    if not any(i.get("title") == title for i in lst):
        lst.append(entry)
        profile[list_key] = lst
        st.session_state.user_profile = profile
        from utils.persistence import save_profile
        save_profile(st.session_state.get("username", ""), profile)
        st.toast(f"{'📌 Added to Watchlist' if list_key == 'watchlist' else '❤️ Added to Favourites'}: {title}")
    else:
        st.toast(f"Already in your {list_key.replace('_',' ').title()}!")



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
    if not recs:
        return
    # Check if recs are dicts with poster_url → use carousel, else use simple list
    has_posters = any(isinstance(r, dict) and r.get("poster_url") for r in recs)
    if has_posters:
        _render_poster_carousel(recs, label="Recommended Films")
        return
    # String or dict without poster
    st.markdown("**🎬 Recommendations**")
    for rec in recs[:8]:
        title = rec.get("title", str(rec)) if isinstance(rec, dict) else str(rec)
        if st.button(f"▶  {title}", key=f"rec_{title[:20]}"):
            _inject_user_message(f"Tell me about {title}")


def _render_poster_carousel(items: list, label: str = "Recommended") -> None:
    cards_html = ""
    for item in items[:12]:
        title = item.get("title", "") if isinstance(item, dict) else str(item)
        poster = item.get("poster_url", "") if isinstance(item, dict) else ""
        cards_html += f"""
        <div style="min-width:130px; max-width:130px; flex-shrink:0; text-align:center;">
            {'<img src="' + poster + '" style="width:120px; height:180px; object-fit:cover; border-radius:8px; border:1px solid #333;">' if poster else '<div style="width:120px; height:180px; background:#1a1a2e; border-radius:8px; display:flex; align-items:center; justify-content:center; font-size:2rem; border:1px solid #333;">🎬</div>'}
            <div style="font-size:0.77rem; margin-top:5px; color:#eaeaea; font-weight:500; word-break:break-word;">{title}</div>
        </div>"""
    st.markdown(f"""
<div style="margin:12px 0;">
    <div style="font-size:0.85rem; color:#a0a0b8; font-weight:600; margin-bottom:8px;">{label}</div>
    <div style="display:flex; gap:12px; overflow-x:auto; padding-bottom:8px;
         scrollbar-width:thin; scrollbar-color:#333 transparent;">
        {cards_html}
    </div>
</div>""", unsafe_allow_html=True)


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
