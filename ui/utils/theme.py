"""
FilmDB – Production CSS Design System
======================================
Deep cinematic dark theme with gold accent, glassmorphism,
micro-animations, and ChatGPT-class message bubbles.
Typography: Google Fonts – Inter.
"""

import streamlit as st

# ── colour tokens ──────────────────────────────────────────────
BG_PRIMARY    = "#0d0d0d"
BG_SURFACE    = "#141422"
BG_CARD       = "#1a1a2e"
BG_ELEVATED   = "#22223a"
BG_SIDEBAR    = "#0d0d0d"
BG_INPUT      = "#1e1e32"

TEXT_PRIMARY   = "#eaeaea"
TEXT_SECONDARY = "#a0a0b8"
TEXT_MUTED     = "#6c6c80"

ACCENT_GOLD   = "#c9a227"
ACCENT_BLUE   = "#3a7bd5"
ACCENT_HOVER  = "#e2c044"

USER_BUBBLE   = "linear-gradient(135deg, #1b3a6b 0%, #22447a 100%)"
ASST_BUBBLE   = "#111"

BORDER_SUBTLE = "rgba(255,255,255,0.06)"
SHADOW_SM     = "0 1px 3px rgba(0,0,0,.35)"
SHADOW_MD     = "0 4px 14px rgba(0,0,0,.45)"
SHADOW_LG     = "0 8px 30px rgba(0,0,0,.55)"

RADIUS_SM     = "8px"
RADIUS_MD     = "12px"
RADIUS_LG     = "18px"
RADIUS_FULL   = "24px"


def load_css() -> None:
    """Inject the full production CSS into Streamlit."""
    st.markdown(f"""
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">

    <style>
    /* ═══════════════════  GLOBAL RESET  ═══════════════════ */
    *, *::before, *::after {{ box-sizing: border-box; }}

    html, body, [data-testid="stAppViewContainer"],
    [data-testid="stApp"] {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
        background-color: {BG_PRIMARY} !important;
        color: {TEXT_PRIMARY} !important;
    }}

    /* ═══════════════════  SCROLLBAR  ═══════════════════ */
    ::-webkit-scrollbar {{ width: 6px; }}
    ::-webkit-scrollbar-track {{ background: transparent; }}
    ::-webkit-scrollbar-thumb {{
        background: {TEXT_MUTED};
        border-radius: 3px;
    }}
    ::-webkit-scrollbar-thumb:hover {{ background: {TEXT_SECONDARY}; }}

    /* ═══════════════════  HIDE DEFAULTS  ═══════════════════ */
    #MainMenu, footer, [data-testid="stDeployButton"] {{ display: none !important; }}
    
    header {{
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
        height: 3rem !important; /* Ensure header has height for toggle */
    }}
    
    /* Ensure the sidebar toggle icon is visible and consistent with theme */
    button[data-testid="stSidebarCollapseButton"] {{
        color: {TEXT_SECONDARY} !important;
        background-color: transparent !important;
        z-index: 1000001 !important;
    }}
    button[data-testid="stSidebarCollapseButton"]:hover {{
        color: {ACCENT_GOLD} !important;
        background-color: rgba(255,255,255,0.05) !important;
    }}

    /* ═══════════════════  SIDEBAR  ═══════════════════ */
    section[data-testid="stSidebar"] {{
        background: {BG_SIDEBAR} !important;
        border-right: 1px solid {BORDER_SUBTLE} !important;
        padding: 1.5rem 1rem !important;
    }}
    section[data-testid="stSidebar"] .stMarkdown p,
    section[data-testid="stSidebar"] .stMarkdown li,
    section[data-testid="stSidebar"] label {{
        color: {TEXT_SECONDARY} !important;
        font-size: 0.88rem !important;
    }}
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {{
        color: {TEXT_PRIMARY} !important;
        font-weight: 600 !important;
    }}
    section[data-testid="stSidebar"] hr {{
        border-color: {BORDER_SUBTLE} !important;
        margin: 0.8rem 0 !important;
    }}

    /* ═══════════════════  BUTTONS (SIDEBAR)  ═══════════════════ */
    section[data-testid="stSidebar"] .stButton > button {{
        width: 100% !important;
        background: transparent !important;
        color: {TEXT_SECONDARY} !important;
        border: 1px solid {BORDER_SUBTLE} !important;
        border-radius: {RADIUS_SM} !important;
        padding: 0.55rem 1rem !important;
        font-size: 0.88rem !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 500 !important;
        text-align: left !important;
        transition: all 0.2s ease !important;
        cursor: pointer !important;
    }}
    section[data-testid="stSidebar"] .stButton > button:hover {{
        background: {BG_ELEVATED} !important;
        color: {ACCENT_GOLD} !important;
        border-color: {ACCENT_GOLD} !important;
        box-shadow: {SHADOW_SM} !important;
    }}

    /* ── new chat accent button ── */
    section[data-testid="stSidebar"] .stButton > button[kind="primary"],
    .new-chat-btn > button {{
        background: linear-gradient(135deg, {ACCENT_GOLD}, #d4a017) !important;
        color: #0d0d0d !important;
        border: none !important;
        font-weight: 600 !important;
        text-align: center !important;
    }}
    .new-chat-btn > button:hover {{
        filter: brightness(1.12) !important;
        box-shadow: 0 0 16px rgba(201,162,39,.35) !important;
    }}

    /* ═══════════════════  MAIN AREA  ═══════════════════ */
    .block-container {{
        max-width: 860px !important;
        padding: 2rem 2rem 6rem 2rem !important;
    }}

    /* ═══════════════════  CHAT INPUT  ═══════════════════ */
    [data-testid="stChatInput"] {{
        background: {BG_INPUT} !important;
        border: 1px solid {BORDER_SUBTLE} !important;
        border-radius: {RADIUS_LG} !important;
        box-shadow: {SHADOW_MD} !important;
    }}
    [data-testid="stChatInput"] textarea {{
        color: {TEXT_PRIMARY} !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 0.95rem !important;
    }}
    [data-testid="stChatInput"] button {{
        color: {ACCENT_GOLD} !important;
    }}

    /* ═══════════════════  CHAT MESSAGE CONTAINERS  ═══════════════════ */
    [data-testid="stChatMessage"] {{
        background: transparent !important;
        border: none !important;
        padding: 0 !important;
        margin-bottom: 0.5rem !important;
    }}

    /* ═══════════════════  BUBBLE SYSTEM  ═══════════════════ */
    .filmdb-user-msg {{
        background: {USER_BUBBLE};
        color: #e8eaf6;
        padding: 0.85rem 1.15rem;
        border-radius: {RADIUS_LG} {RADIUS_LG} 4px {RADIUS_LG};
        max-width: 78%;
        margin-left: auto;
        margin-bottom: 1rem;
        font-size: 0.93rem;
        line-height: 1.6;
        box-shadow: {SHADOW_SM};
        animation: bubbleIn 0.25s ease-out;
        word-wrap: break-word;
    }}
    .filmdb-asst-msg {{
        background: {ASST_BUBBLE};
        color: {TEXT_PRIMARY};
        padding: 1rem 1.25rem;
        border-radius: 4px {RADIUS_LG} {RADIUS_LG} {RADIUS_LG};
        max-width: 88%;
        margin-right: auto;
        margin-bottom: 1rem;
        font-size: 0.93rem;
        line-height: 1.75;
        box-shadow: {SHADOW_SM};
        animation: bubbleIn 0.3s ease-out;
        word-wrap: break-word;
    }}
    .filmdb-asst-msg h1, .filmdb-asst-msg h2, .filmdb-asst-msg h3,
    .filmdb-asst-msg h4, .filmdb-asst-msg h5 {{
        color: {ACCENT_GOLD} !important;
        margin-top: 0.9rem;
        font-weight: 600;
    }}
    .filmdb-asst-msg strong {{ color: {ACCENT_HOVER}; }}
    .filmdb-asst-msg ul, .filmdb-asst-msg ol {{
        padding-left: 1.3rem;
        margin: 0.4rem 0;
    }}
    .filmdb-asst-msg li {{ margin-bottom: 0.25rem; }}
    .filmdb-asst-msg code {{
        background: rgba(255,255,255,0.07);
        padding: 0.15rem 0.4rem;
        border-radius: 4px;
        font-size: 0.87rem;
    }}
    .filmdb-asst-msg a {{
        color: {ACCENT_GOLD};
        text-decoration: none;
    }}
    .filmdb-asst-msg a:hover {{ text-decoration: underline; }}

    @keyframes bubbleIn {{
        from {{ opacity: 0; transform: translateY(8px); }}
        to   {{ opacity: 1; transform: translateY(0); }}
    }}

    /* ═══════════════════  POSTER / MEDIA CARD  ═══════════════════ */
    .filmdb-poster-card {{
        background: {BG_CARD};
        border: 1px solid {BORDER_SUBTLE};
        border-radius: {RADIUS_MD};
        overflow: hidden;
        box-shadow: {SHADOW_MD};
        transition: transform 0.22s ease, box-shadow 0.22s ease;
    }}
    .filmdb-poster-card:hover {{
        transform: translateY(-3px);
        box-shadow: {SHADOW_LG};
    }}
    .filmdb-poster-card img {{
        width: 100%;
        border-radius: {RADIUS_MD} {RADIUS_MD} 0 0;
    }}

    /* ═══════════════════  PLATFORM BADGES  ═══════════════════ */
    .filmdb-platform-badge {{
        display: inline-block;
        background: {BG_ELEVATED};
        color: {ACCENT_GOLD};
        font-size: 0.8rem;
        font-weight: 600;
        padding: 0.3rem 0.75rem;
        border-radius: 50px;
        border: 1px solid rgba(201,162,39,.25);
        margin: 0.2rem 0.25rem;
        transition: all 0.2s ease;
    }}
    .filmdb-platform-badge:hover {{
        background: rgba(201,162,39,.15);
        border-color: {ACCENT_GOLD};
    }}

    /* ═══════════════════  RECOMMENDATION GRID  ═══════════════════ */
    .filmdb-rec-card {{
        background: {BG_CARD};
        border: 1px solid {BORDER_SUBTLE};
        border-radius: {RADIUS_MD};
        padding: 0.75rem;
        text-align: center;
        cursor: pointer;
        transition: all 0.22s ease;
    }}
    .filmdb-rec-card:hover {{
        border-color: {ACCENT_GOLD};
        transform: translateY(-2px);
        box-shadow: 0 0 18px rgba(201,162,39,.15);
    }}
    .filmdb-rec-card img {{
        border-radius: {RADIUS_SM};
        width: 100%;
        margin-bottom: 0.4rem;
    }}
    .filmdb-rec-title {{
        font-weight: 600;
        font-size: 0.85rem;
        color: {TEXT_PRIMARY};
    }}

    /* ═══════════════════  STARTER CARDS  ═══════════════════ */
    .filmdb-starter {{
        background: {BG_CARD};
        border: 1px solid {BORDER_SUBTLE};
        border-radius: {RADIUS_MD};
        padding: 1.4rem 1rem;
        text-align: center;
        cursor: pointer;
        transition: all 0.25s ease;
        min-height: 100px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
    }}
    .filmdb-starter:hover {{
        border-color: {ACCENT_GOLD};
        background: {BG_ELEVATED};
        box-shadow: 0 0 22px rgba(201,162,39,.12);
        transform: translateY(-3px);
    }}
    .filmdb-starter-icon {{
        font-size: 1.6rem;
        margin-bottom: 0.5rem;
    }}
    .filmdb-starter-label {{
        font-size: 0.88rem;
        font-weight: 600;
        color: {TEXT_SECONDARY};
    }}
    .filmdb-starter:hover .filmdb-starter-label {{
        color: {ACCENT_GOLD};
    }}

    /* ═══════════════════  SOURCES EXPANDER  ═══════════════════ */
    .filmdb-sources-toggle {{
        background: {BG_CARD};
        border: 1px solid {BORDER_SUBTLE};
        border-radius: {RADIUS_SM};
        padding: 0.5rem 0.9rem;
        margin-top: 0.4rem;
        font-size: 0.82rem;
        color: {TEXT_SECONDARY};
        cursor: pointer;
        transition: background 0.2s ease;
    }}
    .filmdb-sources-toggle:hover {{
        background: {BG_ELEVATED};
        color: {ACCENT_GOLD};
    }}

    /* ═══════════════════  AUTH  ═══════════════════ */
    .filmdb-auth-card {{
        background: {BG_CARD};
        border: 1px solid {BORDER_SUBTLE};
        border-radius: {RADIUS_LG};
        padding: 2.5rem 2.5rem 2rem 2.5rem;
        width: 100%;
        max-width: 420px;
        box-shadow: {SHADOW_LG};
        animation: fadeUp 0.45s ease;
    }}
    .filmdb-auth-card h2 {{
        text-align: center;
        font-weight: 700;
        margin-bottom: 0.3rem;
        color: {TEXT_PRIMARY};
    }}
    .filmdb-auth-card .subtitle {{
        text-align: center;
        color: {TEXT_MUTED};
        font-size: 0.88rem;
        margin-bottom: 1.6rem;
    }}

    .filmdb-profile-card {{
        background: {BG_CARD};
        border: 1px solid {BORDER_SUBTLE};
        border-radius: {RADIUS_LG};
        padding: 2.5rem 2.5rem 2rem 2.5rem;
        width: 100%;
        max-width: 580px;
        box-shadow: {SHADOW_LG};
        margin: 0 auto;
        animation: fadeUp 0.45s ease;
    }}

    @keyframes fadeUp {{
        from {{ opacity: 0; transform: translateY(18px); }}
        to   {{ opacity: 1; transform: translateY(0); }}
    }}

    /* ═══════════════════  FORM INPUTS  ═══════════════════ */
    .stTextInput input,
    .stTextArea textarea {{
        background: {BG_INPUT} !important;
        border: 1px solid {BORDER_SUBTLE} !important;
        border-radius: {RADIUS_SM} !important;
        color: {TEXT_PRIMARY} !important;
        font-family: 'Inter', sans-serif !important;
        transition: border 0.2s ease !important;
    }}
    .stTextInput input:focus,
    .stTextArea textarea:focus {{
        border-color: {ACCENT_GOLD} !important;
        box-shadow: 0 0 0 2px rgba(201,162,39,.18) !important;
    }}
    .stSelectbox > div > div,
    .stMultiSelect > div > div {{
        background: {BG_INPUT} !important;
        border: 1px solid {BORDER_SUBTLE} !important;
        border-radius: {RADIUS_SM} !important;
        color: {TEXT_PRIMARY} !important;
    }}

    /* ═══════════════════  FORM SUBMIT BUTTON  ═══════════════════ */
    [data-testid="stFormSubmitButton"] > button {{
        background: linear-gradient(135deg, {ACCENT_GOLD}, #d4a017) !important;
        color: #0d0d0d !important;
        border: none !important;
        border-radius: {RADIUS_SM} !important;
        font-weight: 600 !important;
        font-family: 'Inter', sans-serif !important;
        padding: 0.6rem 1.5rem !important;
        transition: all 0.2s ease !important;
        letter-spacing: 0.02em !important;
    }}
    [data-testid="stFormSubmitButton"] > button:hover {{
        filter: brightness(1.1) !important;
        box-shadow: 0 0 18px rgba(201,162,39,.35) !important;
    }}

    /* ═══════════════════  EXPANDER  ═══════════════════ */
    .streamlit-expanderHeader {{
        background: {BG_CARD} !important;
        border-radius: {RADIUS_SM} !important;
        font-size: 0.85rem !important;
        color: {TEXT_SECONDARY} !important;
    }}
    .streamlit-expanderContent {{
        background: {BG_SURFACE} !important;
        border-radius: 0 0 {RADIUS_SM} {RADIUS_SM} !important;
    }}

    /* ═══════════════════  SPINNER  ═══════════════════ */
    .stSpinner > div {{ color: {ACCENT_GOLD} !important; }}
    .stSpinner > div > div {{
        border-top-color: {ACCENT_GOLD} !important;
    }}

    /* ═══════════════════  TITLE  ═══════════════════ */
    .filmdb-title {{
        font-family: 'Inter', sans-serif;
        font-weight: 800;
        font-size: 1.5rem;
        letter-spacing: -0.02em;
        color: {TEXT_PRIMARY};
        margin-bottom: 0.5rem;
    }}
    .filmdb-title span {{
        color: {ACCENT_GOLD};
    }}

    /* ═══════════════════  KEBAB MENU  ═══════════════════ */
    [data-testid="stPopover"] > button {{
        background: transparent !important;
        border: 1px solid {BORDER_SUBTLE} !important;
        border-radius: {RADIUS_SM} !important;
        color: {TEXT_SECONDARY} !important;
        font-size: 1.2rem !important;
        padding: 0.3rem 0.6rem !important;
        min-height: 2rem !important;
        line-height: 1 !important;
        transition: all 0.2s ease !important;
    }}
    [data-testid="stPopover"] > button:hover {{
        background: {BG_ELEVATED} !important;
        color: {ACCENT_GOLD} !important;
        border-color: {ACCENT_GOLD} !important;
    }}
    [data-testid="stPopoverBody"] {{
        background: {BG_CARD} !important;
        border: 1px solid {BORDER_SUBTLE} !important;
        border-radius: {RADIUS_MD} !important;
        box-shadow: {SHADOW_LG} !important;
        padding: 0.8rem !important;
    }}
    [data-testid="stPopoverBody"] .stButton > button {{
        background: transparent !important;
        color: {TEXT_SECONDARY} !important;
        border: 1px solid {BORDER_SUBTLE} !important;
        border-radius: {RADIUS_SM} !important;
        font-size: 0.85rem !important;
        padding: 0.45rem 0.8rem !important;
        text-align: left !important;
        transition: all 0.2s ease !important;
    }}
    [data-testid="stPopoverBody"] .stButton > button:hover {{
        background: {BG_ELEVATED} !important;
        color: {ACCENT_GOLD} !important;
        border-color: {ACCENT_GOLD} !important;
    }}

    /* ═══════════════════  CHAT HISTORY SEARCH  ═══════════════════ */
    section[data-testid="stSidebar"] .stTextInput input[placeholder*="Search"] {{
        background: {BG_INPUT} !important;
        border: 1px solid {BORDER_SUBTLE} !important;
        border-radius: 20px !important;
        padding: 0.4rem 0.9rem !important;
        font-size: 0.82rem !important;
        color: {TEXT_SECONDARY} !important;
    }}
    section[data-testid="stSidebar"] .stTextInput input[placeholder*="Search"]:focus {{
        border-color: {ACCENT_GOLD} !important;
        box-shadow: 0 0 0 2px rgba(201,162,39,.15) !important;
    }}

    /* ═══════════════════  SIDEBAR PROFILE FOOTER  ═══════════════════ */
    .filmdb-sidebar-profile {{
        position: fixed;
        bottom: 0;
        width: inherit;
        background: {BG_SIDEBAR};
        border-top: 1px solid {BORDER_SUBTLE};
        padding: 0.75rem 1rem;
    }}
    .filmdb-profile-name {{
        font-weight: 600;
        font-size: 0.9rem;
        color: {TEXT_PRIMARY};
    }}
    .filmdb-profile-tag {{
        font-size: 0.75rem;
        color: {TEXT_MUTED};
    }}

    /* ═══════════════════  NEW UI ENHANCEMENTS (Glass, Shimmer, Carousel)  ═══════════════════ */
    
    /* 1. Glassmorphism Cards */
    .filmdb-glass-card {{
        background: rgba(20, 20, 34, 0.6) !important;
        backdrop-filter: blur(14px) !important;
        -webkit-backdrop-filter: blur(14px) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3) !important;
        transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1) !important;
    }}
    .filmdb-glass-card:hover {{
        border-color: rgba(201, 162, 39, 0.4) !important;
        box-shadow: 0 8px 32px 0 rgba(201, 162, 39, 0.15) !important;
        transform: translateY(-2px) !important;
    }}

    /* 2. Shimmer Skeleton Loader (Thinking State) */
    @keyframes shimmerSweep {{
        0% {{ background-position: -200% 0; }}
        100% {{ background-position: 200% 0; }}
    }}
    .filmdb-skeleton {{
        display: flex; gap: 14px; align-items: flex-start; margin-bottom: 20px;
    }}
    .filmdb-skeleton-avatar {{
        width: 38px; height: 38px; border-radius: 50%; flex-shrink: 0;
        background: linear-gradient(90deg, #2c2c44 25%, #4a4a6a 50%, #2c2c44 75%);
        background-size: 200% 100%;
        animation: shimmerSweep 1.5s infinite linear;
    }}
    .filmdb-skeleton-content {{
        flex: 1; display: flex; flex-direction: column; gap: 10px; padding-top: 6px;
    }}
    .filmdb-skeleton-bar {{
        height: 12px; border-radius: 6px;
        background: linear-gradient(90deg, #2c2c44 25%, #4a4a6a 50%, #2c2c44 75%);
        background-size: 200% 100%;
        animation: shimmerSweep 1.5s infinite linear;
    }}
    .filmdb-skeleton-bar:nth-child(1) {{ width: 85%; }}
    .filmdb-skeleton-bar:nth-child(2) {{ width: 60%; }}
    .filmdb-skeleton-bar:nth-child(3) {{ width: 40%; }}

    /* 3. Horizontal Scroll Snap Carousel */
    .filmdb-carousel {{
        display: flex; gap: 16px; overflow-x: auto; padding: 10px 0 20px 0;
        scroll-snap-type: x mandatory;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: thin;
        scrollbar-color: rgba(201, 162, 39, 0.3) transparent;
    }}
    .filmdb-carousel::-webkit-scrollbar {{ height: 6px; }}
    .filmdb-carousel::-webkit-scrollbar-track {{ background: transparent; }}
    .filmdb-carousel::-webkit-scrollbar-thumb {{ background: rgba(201, 162, 39, 0.3); border-radius: 10px; }}
    
    .filmdb-carousel-item {{
        min-width: 140px; max-width: 140px; flex-shrink: 0;
        scroll-snap-align: start;
        border-radius: 10px; overflow: hidden;
        background: rgba(20, 20, 34, 0.8); border: 1px solid rgba(255, 255, 255, 0.05);
        transition: transform 0.3s ease, box-shadow 0.3s ease, border-color 0.3s ease;
        position: relative;
    }}
    .filmdb-carousel-item:hover {{
        transform: translateY(-5px);
        border-color: rgba(201, 162, 39, 0.5);
        box-shadow: 0 10px 20px rgba(0, 0, 0, 0.4), 0 0 15px rgba(201, 162, 39, 0.2);
    }}
    .filmdb-carousel-item img {{
        width: 100%; height: 210px; object-fit: cover; display: block;
    }}
    .filmdb-carousel-meta {{
        padding: 10px; text-align: center;
    }}
    .filmdb-carousel-title {{
        font-size: 0.8rem; font-weight: 600; color: #eaeaea; 
        margin-bottom: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }}
    .filmdb-carousel-sub {{
        font-size: 0.65rem; color: #8e8ea4;
    }}

    /* 4. Interactive Starter Cards (Targeting Streamlit Buttons) */
    /* Target the column divs that contain starter cards to make the buttons fill them beautifully */
    div[data-testid="column"]:has(.filmdb-starter-hook) button[kind="secondary"] {{
        width: 100% !important;
        height: 110px !important;
        background: linear-gradient(145deg, rgba(20, 20, 34, 0.8) 0%, rgba(15, 15, 25, 0.95) 100%) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 14px !important;
        padding: 18px 20px !important;
        text-align: left !important;
        display: flex !important;
        flex-direction: column !important;
        justify-content: space-between !important;
        transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1) !important;
        position: relative !important;
        overflow: hidden !important;
    }}
    
    div[data-testid="column"]:has(.filmdb-starter-hook) button[kind="secondary"] p {{
        font-size: 0.95rem !important;
        font-weight: 600 !important;
        color: #eaeaea !important;
        white-space: normal !important;
        line-height: 1.4 !important;
        margin: 0 !important;
    }}

    div[data-testid="column"]:has(.filmdb-starter-hook) button[kind="secondary"]:hover {{
        border-color: rgba(201, 162, 39, 0.6) !important;
        transform: translateY(-3px) !important;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4), 0 0 15px rgba(201, 162, 39, 0.15) !important;
    }}

    /* Add animated glowing border effect on hover using pseudoelements */
    div[data-testid="column"]:has(.filmdb-starter-hook) button[kind="secondary"]::after {{
        content: ""; position: absolute; top: 0; left: -100%; width: 50%; height: 100%;
        background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.05), transparent);
        transform: skewX(-20deg); transition: 0s;
    }}
    div[data-testid="column"]:has(.filmdb-starter-hook) button[kind="secondary"]:hover::after {{
        left: 200%; transition: 0.7s ease-in-out;
    }}

    /* 5. Download Card Pulse Animation */
    @keyframes downloadPulse {{
        0% {{ box-shadow: 0 0 0 0 rgba(201, 162, 39, 0.4); }}
        70% {{ box-shadow: 0 0 0 10px rgba(201, 162, 39, 0); }}
        100% {{ box-shadow: 0 0 0 0 rgba(201, 162, 39, 0); }}
    }}
    .filmdb-download-card {{
        background: rgba(26, 26, 46, 0.9);
        border: 1px solid rgba(201, 162, 39, 0.4);
        border-radius: 12px; padding: 16px 20px; margin-top: 15px;
        display: flex; align-items: center; gap: 16px;
        animation: downloadPulse 2.5s infinite;
        transition: transform 0.2s ease;
    }}
    .filmdb-download-card:hover {{
        transform: scale(1.01);
    }}
    .filmdb-download-btn {{
        background: linear-gradient(135deg, #c9a227, #d4a017);
        color: #0d0d0d !important; padding: 10px 20px; border-radius: 8px;
        font-weight: 700; font-size: 0.9rem; text-decoration: none !important;
        transition: all 0.2s ease; display: inline-block;
        box-shadow: 0 4px 15px rgba(201, 162, 39, 0.3);
    }}
    .filmdb-download-btn:hover {{
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(201, 162, 39, 0.5);
        color: #000 !important;
    }}

    /* 6. Staggered Fade-In Animations */
    @keyframes staggerFadeIn {{
        from {{ opacity: 0; transform: translateY(15px); }}
        to {{ opacity: 1; transform: translateY(0); }}
    }}
    .filmdb-stagger-item {{
        opacity: 0;
        animation: staggerFadeIn 0.5s cubic-bezier(0.25, 0.8, 0.25, 1) forwards;
    }}

    /* ═══════════════════  MISC  ═══════════════════ */
    .stAlert {{ border-radius: {RADIUS_SM} !important; }}
    div[data-testid="stImage"] {{ border-radius: {RADIUS_SM}; overflow: hidden; }}
    </style>
    """, unsafe_allow_html=True)
