# 🎬 FilmDB -- Demo

## 🍿 UI Architecture Specification

**Version:** 1.0\
**Date:** 2026-03-02\
**Purpose:** Production-Ready UI Architecture for Streamlit Frontend\
**Backend Compatibility:** FastAPI + Deterministic ConversationEngine

------------------------------------------------------------------------

# 1. Executive Summary

This document defines the complete UI architecture for **FilmDB --
Demo**, a personalized cinematic intelligence chatbot built with:

-   Streamlit (Frontend UI Layer)
-   FastAPI (API Layer)
-   Deterministic Intent-Governed Orchestration Backend

The UI must:

-   Replicate a ChatGPT-like experience
-   Be personalized and profile-aware
-   Render responses deterministically using `response_mode`
-   Be professional, clean, and production-oriented

------------------------------------------------------------------------

# 2. Design Philosophy

## Core Principles

1.  Deterministic Rendering (No layout inference)
2.  Personalized Experience (UserProfile-driven)
3.  Professional & Minimal Aesthetic
4.  High Readability & Scroll Performance
5.  Clear Structural Separation (UI ≠ Logic)

------------------------------------------------------------------------

# 3. Application Layout Structure

    ----------------------------------------------------------
    | Sidebar  |  Main Chat Area                  |  (⋮)  |
    |          |--------------------------------------------|
    |Search 🔍 | Title: 🍿 FilmDB – Demo                    |
    |New Chat  |                                            |
    |History   | Scrollable Chat Container                  |
    |Features  |                                            |
    |          |--------------------------------------------|
    | Profile  | Input Field + Send Button                 |
    ----------------------------------------------------------

------------------------------------------------------------------------

# 4. Authentication & Onboarding Flow

## 4.1 First Launch Behavior

When a new user opens the application:

-   Background blurred
-   Login modal displayed
-   Chat disabled until authentication

------------------------------------------------------------------------

## 4.2 Login Modal

### Required Fields

-   Name (Username)
-   Password

### Backend Storage

Stored in:

-   `User`
-   `UserProfile`

Passwords must be hashed (bcrypt).

------------------------------------------------------------------------

# 5. Personalization Modal (First-Time Users)

After successful login, a dynamic modal appears.

## Mandatory Fields

### Region (Dropdown)

-   India
-   USA
-   UK
-   Canada
-   Australia
-   Germany
-   France
-   Japan
-   South Korea
-   Other

### Favorite Genres (Select ≥3)

-   Action
-   Sci-Fi
-   Drama
-   Thriller
-   Romance
-   Comedy
-   Horror
-   Fantasy
-   Crime
-   Adventure
-   Animation
-   Documentary

### Subscribed Platforms (Multi-Select)

-   Netflix
-   Prime Video
-   Disney+
-   Hotstar
-   Apple TV+
-   Hulu
-   HBO
-   Zee5
-   SonyLIV
-   YouTube Movies

### Favorite Movies (≥1 Required)

### Favorite Actor/Actress (≥1 Required)

### Favorite Director (≥1 Required)

------------------------------------------------------------------------

# 6. Chat Interface Architecture

## 6.1 Title Area

**🍿 FilmDB -- Demo**

-   Professional typography (Inter).
-   Clean title bar without subtitles for a minimal look.
-   Kebab Menu (⋮) located in the top-right corner for session management.

------------------------------------------------------------------------

## 6.5 Chat Management (Kebab Menu)

A three-dot popover menu in the top-right allows:

-   **Rename Chat:** Manually override the auto-generated title.
-   **Clear Chat:** Empties all messages while retaining the `session_id`.
-   **Delete Chat:** Permanently removes the session from history and starts a new one.

------------------------------------------------------------------------

## 6.2 Chat Container

-   Vertically scrollable
-   Height: 70--75vh
-   Smooth scroll
-   Copy button on hover
-   No avatar icons
-   Rounded message bubbles

------------------------------------------------------------------------

## 6.3 User Bubble

-   Right aligned
-   Soft blue background
-   Subtle shadow

## 6.4 Assistant Bubble

-   Left aligned
-   Light neutral background
-   Structured markdown support

------------------------------------------------------------------------

# 7. Input Area

-   Multi-line input
-   Enter → Send
-   Shift + Enter → New line
-   Send button on right
-   No file upload
-   No attachment options

------------------------------------------------------------------------

# 8. Loading & Streaming Behavior

When user sends message:

1.  Disable input
2.  Show spinner: "Fetching cinematic intelligence..."
3.  Stream or simulate streaming text

------------------------------------------------------------------------

# 9. Response Rendering Engine

UI must render based strictly on:

    response["response_mode"]

## Supported Modes

-   FULL_CARD
-   MINIMAL_CARD
-   EXPLANATION_ONLY
-   EXPLANATION_PLUS_AVAILABILITY
-   AVAILABILITY_FOCUS
-   RECOMMENDATION_GRID
-   CLARIFICATION

------------------------------------------------------------------------

# 10. Structured Components

## 10.1 FULL_CARD

-   Poster (left)
-   Metadata + Explanation (right)
-   Streaming block
-   Recommendation grid

## 10.2 RECOMMENDATION_GRID

-   3-column layout
-   Poster + Title
-   Click-to-query functionality

## 10.3 AVAILABILITY_FOCUS

-   Platform cards
-   Region badge
-   Minimal explanation

------------------------------------------------------------------------

# 11. Collapsible Sources Panel

If response contains sources:

    Sources ▾

Collapsed by default.

Displays clickable links.

------------------------------------------------------------------------

# 12. Starter Prompt Cards (Fresh Chat Only)

When no messages exist, show:

-   🔥 Trending Tamil
-   🏆 Top Rated English
-   🎬 Upcoming Releases
-   📺 What's New on My Platforms

Cards disappear after first user interaction.

------------------------------------------------------------------------

# 13. Sidebar Architecture

## 13.1 Chat Search

-   Real-time filtering via search box at the top of the history list.
-   Searches through chat titles.
-   Persistent search state in `session_state`.

## 13.2 New Chat

-   Creates a fresh `session_id`.
-   Clears the active message screen.
-   Immediately accessible via a prominent gold button.

## 13.3 Chat History (Always Visible)

-   **Auto-Naming:** Automatically generates a title from the first message.
-   **Sorting:** Newest sessions appear at the top.
-   **Limit:** Displays the last 30 sessions.
-   **Quick Actions:** Rename (✏️) and Delete (🗑) buttons directly on each history item.
-   **Persistent:** History is reloaded from disk on app launch and saved after every assistant response.

------------------------------------------------------------------------

# 14. Sidebar Feature Shortcuts

-   🎥 Similar Films
-   📺 Streaming Availability
-   🔥 Trending
-   🏆 Top Rated
-   🎬 Upcoming
-   🎭 Personality Lookup

------------------------------------------------------------------------

# 15. Bottom Profile Section

Clicking user name opens:

-   View Profile
-   Personalization
-   Settings
-   Delete Data
-   Delete Account

------------------------------------------------------------------------

# 16. Theme System

## Light Mode

White background, dark text.

## Dark Mode

Charcoal background, light text.

Toggle stored in session state.

------------------------------------------------------------------------

# 17. Data Management

## Delete Data

Removes all chat sessions.

## Delete Account

Deletes:

-   User
-   UserProfile
-   Sessions
-   Messages
-   SessionContext

------------------------------------------------------------------------

# 18. UX Enhancements

-   Smooth animations
-   Hover elevation on cards
-   Clean spacing
-   No clutter
-   Consistent padding
-   Professional color palette

Primary Color: Deep Blue\
Accent: Gold\
Background: White / Charcoal

------------------------------------------------------------------------

# 19. Security Considerations

-   Hash passwords
-   Validate username uniqueness
-   Prevent SQL injection
-   Protect API endpoints

------------------------------------------------------------------------

# 20. Final Architecture Summary

FilmDB UI delivers:

-   ChatGPT-like experience
-   Personalized cinematic intelligence
-   Deterministic rendering
-   Profile-aware recommendations
-   Professional, scalable UI system

------------------------------------------------------------------------

# End of Document
