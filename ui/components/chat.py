"""
FilmDB – Chat Interface & Sidebar
===================================
Production-grade ChatGPT-like chat with:
• Deterministic response_mode rendering (FULL_CARD, RECOMMENDATION_GRID, etc.)
• Animated message bubbles with markdown support
• Sidebar with chat history, feature shortcuts, and profile section
• Starter prompt cards for empty sessions
"""

import streamlit as st
from utils.state import new_chat_session, restore_chat_session, delete_chat_session
from utils.markdown_renderer import md_to_html
from utils.persistence import clear_last_active_user
from api_client import send_chat_message


# ═══════════════════════════════════════════════════════════════
#  SIDEBAR
# ═══════════════════════════════════════════════════════════════

def render_sidebar() -> None:
    with st.sidebar:
        # ── branding ──
        st.markdown(
            "<div style='text-align:center;margin-bottom:0.5rem;'>"
            "<span style='font-size:1.4rem;font-weight:800;letter-spacing:-0.02em;'>"
            "🍿 <span style='color:#c9a227;'>Film</span>DB</span></div>",
            unsafe_allow_html=True,
        )

        # ── new chat ──
        st.markdown("<div class='new-chat-btn'>", unsafe_allow_html=True)
        if st.button("＋  New Chat", key="btn_new_chat", use_container_width=True):
            new_chat_session()
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("---")

        # ── feature shortcuts ──
        st.markdown(
            "<p style='font-size:0.72rem;text-transform:uppercase;"
            "letter-spacing:0.08em;color:#6c6c80;font-weight:600;"
            "margin-bottom:0.3rem;'>Quick Actions</p>",
            unsafe_allow_html=True,
        )
        _shortcuts = [
            ("🎥", "Find Similar Films"),
            ("📺", "Streaming Availability"),
            ("🔥", "Trending Now"),
            ("🏆", "Top Rated"),
            ("🎬", "Upcoming Releases"),
            ("🎭", "Actor / Director Lookup"),
        ]
        for icon, label in _shortcuts:
            if st.button(f"{icon}  {label}", key=f"sc_{label}"):
                _inject_user_message(label)

        st.markdown("---")

        # ── chat history ──
        sessions = st.session_state.get("chat_sessions", {})
        if sessions:
            st.markdown(
                "<p style='font-size:0.72rem;text-transform:uppercase;"
                "letter-spacing:0.08em;color:#6c6c80;font-weight:600;"
                "margin-bottom:0.3rem;'>History</p>",
                unsafe_allow_html=True,
            )
            for sid, meta in list(sessions.items())[:15]:  # cap display
                col_title, col_del = st.columns([5, 1])
                with col_title:
                    if st.button(
                        f"💬 {meta['title']}",
                        key=f"hist_{sid}",
                        use_container_width=True,
                    ):
                        restore_chat_session(sid)
                        st.rerun()
                with col_del:
                    if st.button("🗑", key=f"del_{sid}"):
                        delete_chat_session(sid)
                        st.rerun()

            st.markdown("---")

        # ── profile footer ──
        username = st.session_state.get("username", "User")
        region = st.session_state.get("user_profile", {}).get("region", "")
        st.markdown(
            f"<div style='margin-top:1rem;'>"
            f"<span class='filmdb-profile-name'>👤 {username}</span><br>"
            f"<span class='filmdb-profile-tag'>{region}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        if st.button("Logout", key="btn_logout"):
            clear_last_active_user()
            st.session_state.clear()
            st.rerun()


# ═══════════════════════════════════════════════════════════════
#  MAIN CHAT INTERFACE
# ═══════════════════════════════════════════════════════════════

def render_chat_interface() -> None:
    # ── title bar ──
    st.markdown(
        "<div class='filmdb-title'>🍿 <span>Film</span>DB</div>"
        "<div class='filmdb-subtitle'>Personalised cinematic intelligence — powered by deterministic AI</div>",
        unsafe_allow_html=True,
    )

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
#  STARTER PROMPT CARDS
# ═══════════════════════════════════════════════════════════════

def _render_starter_cards() -> None:
    cards = [
        ("🔥", "Trending Tamil"),
        ("🏆", "Top Rated English"),
        ("🎬", "Upcoming Releases"),
        ("📺", "What's New on My Platforms"),
    ]
    cols = st.columns(len(cards), gap="medium")
    for idx, (icon, label) in enumerate(cards):
        with cols[idx]:
            st.markdown(
                f"<div class='filmdb-starter'>"
                f"<div class='filmdb-starter-icon'>{icon}</div>"
                f"<div class='filmdb-starter-label'>{label}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
            if st.button("Ask", key=f"starter_{idx}", use_container_width=True):
                _inject_user_message(label)


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
        col_poster, col_text = st.columns([1, 2.5], gap="medium")
        with col_poster:
            st.markdown("<div class='filmdb-poster-card'>", unsafe_allow_html=True)
            st.image(poster, use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
        with col_text:
            st.markdown(
                f"<div class='filmdb-asst-msg'>{md_to_html(text)}</div>",
                unsafe_allow_html=True,
            )
            if streaming:
                _render_platforms(streaming)
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
        # Show recommendations in any mode if present
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
    st.markdown(
        "<p style='font-size:0.78rem;color:#a0a0b8;font-weight:600;"
        "margin:0.8rem 0 0.4rem;text-transform:uppercase;letter-spacing:0.06em;'>"
        "You might also like</p>",
        unsafe_allow_html=True,
    )
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
                # Click-to-query
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
    st.rerun()
