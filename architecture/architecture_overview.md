# 🎬 FilmDB - Demo

## Core Backend Architecture Documentation

------------------------------------------------------------------------

# 1️ Introduction

This document explains the complete backend architecture of the
FilmDB - Demo project.


The system follows an **LLM-first, tool-grounded hybrid architecture**.

Core Philosophy:

-   LLM is the primary reasoning engine
-   Backend governs tool execution
-   Tools provide verified factual data
-   Memory is stored externally
-   Personalization is injected dynamically
-   Tool calls are governed (not rigidly routed)
-   Async parallel execution is supported
-   Graceful degradation is mandatory
-   Maximum 3 tool calls per request
-   Clean modular design
-   One retry on failure before marking error

------------------------------------------------------------------------

# 2️ High-Level Architecture

  User Request
        ↓
  Load Session Memory + User Profile
        ↓
  LLM Proposes Tool Calls
        ↓
  Tool Governance Layer
        ↓
  Enforce Max Tool Calls (3)
        ↓
  Async Parallel Tool Execution
        ↓
  Normalize Tool Outputs
        ↓
  Construct Structured Prompt
        ↓
  Final LLM Synthesis
        ↓
  Store Conversation + Return Response

This is NOT a multi-agent system.

It is a single orchestrated conversational intelligence pipeline.

------------------------------------------------------------------------

# 3️ Core Backend Components

## 3.1 API Layer (FastAPI)

Responsibilities:

-   Accept user message
-   Attach session ID
-   Fetch user profile
-   Call conversation engine
-   Return structured JSON

Example Endpoint:

``` python
POST /chat
{
  "session_id": "...",
  "user_id": "...",
  "message": "Is The Godfather streaming in India?"
}
```

------------------------------------------------------------------------

## 3.2 Conversation Engine (Orchestrator)

This is the brain controller.

Responsibilities:

1.  Load session memory (last 8 messages max)
2.  Load user profile
3.  Ask LLM if tools are needed
4.  Validate tool calls
5.  Enforce max tool limit (3)
6.  Execute approved tools
7.  Construct structured LLM prompt
8.  Call LLM for final response
9.  Store conversation
10. Return structured output

The conversation engine never lets tools talk to each other.

------------------------------------------------------------------------

# 4️ Tool Services Layer

Each tool is stateless and independent.

Tools:

  Tool                    Purpose
  ----------------------- ----------------------
  IMDb API                Metadata
  DiscoveryEngine (IMDb)  Trending / Top Rated / Upcoming lists
  IMDb Personality        Person profiles / filmography
  Rotten Tomatoes         Critics sentiment (score only)
  Wikipedia               Overview / Biography
  Watchmode               Streaming
  Similarity Engine       Recommendations
  Archive                 Legal download
  Web Search (Serp.dev)   Freshness + Reviews

Each tool must return standardized output:

``` python
{
    "status": "success" | "not_found" | "error",
    "data": {...}
}
```

Never pass raw API responses to the LLM.

------------------------------------------------------------------------

# 5️ Tool Governance Layer

This layer prevents:

-   Unnecessary tool calls
-   Tool cascades
-   Cost explosion
-   Latency spikes

Rules:

-   Tool must exist in registry
-   Parameters must match schema
-   Tool must match query relevance
-   Maximum 3 tool calls per request
-   Similarity tool only if recommendations requested
-   Archive tool only if download requested
-   Retry failed tools once

------------------------------------------------------------------------

# 6️ Memory Architecture

## 6.1 Short-Term Memory (Session)

Stored in DB:

``` json
{
  "session_id": "...",
  "messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

Only inject last 8 messages to LLM.

------------------------------------------------------------------------

## 6.2 Long-Term Memory (User Profile)

``` json
{
  "user_id": "...",
  "region": "India",
  "preferred_language": "English",
  "subscribed_platforms": ["Netflix"],
  "favorite_genres": ["Sci-Fi"],
  "favorite_movies": ["Interstellar"]
}
```

Inject selectively.

LLM does NOT own memory.

------------------------------------------------------------------------

# 7️ Prompt Construction Template

The prompt must follow structured layering:

    SYSTEM:
    [Static system instructions]

    USER PROFILE:
    [Injected if relevant]

    RECENT CONVERSATION:
    [last 8 exchanges]

    TOOL DATA:
    [Structured tool summaries]

    USER QUERY:
    [current message]

Never dump raw JSON.

------------------------------------------------------------------------

# 8️ Error Handling Strategy

Graceful degradation philosophy:

If a tool fails:

-   Mark status
-   Inform LLM clearly
-   Continue answering with available data
-   Never hallucinate missing facts

Retry strategy:

-   One retry on timeout
-   If still fails → mark "temporarily unavailable"

------------------------------------------------------------------------

# 9️ Response Output Schema

Backend returns:

``` json
{
  "text_response": "...",
  "poster_url": "...",
  "streaming": [...],
  "recommendations": [...],
  "download_link": "...",
  "sources": [...]
}
```

Frontend handles layout.

LLM handles language.

------------------------------------------------------------------------

# 10 Full Workflow Example

User Query:

"Why is The Godfather considered a GOAT film? What praise did it get?
Where can I stream it?"

Flow:

1.  Detect movie entity
2.  LLM proposes tool calls
3.  Governance validates tools
4.  Call IMDb
5.  Call Watchmode
6.  Call Web Search
7.  Format tool data
8.  Construct prompt
9.  Call LLM
10. Save conversation
11. Return structured output

------------------------------------------------------------------------

# 1️1️ Cost Control Strategy

-   Max 3 tool calls
-   Cache metadata for 24 hours
-   Cache streaming results for 24 hours
-   Cache similarity results
-   Avoid redundant calls in same session

------------------------------------------------------------------------

# 1️2️ Final Philosophy

This architecture is:

-   LLM-first
-   Fact-grounded
-   Personalized
-   Governed
-   Scalable
-   Demo-ready
-   Production-safe in design thinking

It balances creative intelligence with controlled execution.

------------------------------------------------------------------------

# Closing Note for Code Agent

When building this system:

-   Keep services modular
-   Never mix tool logic with orchestration
-   Keep prompt construction disciplined
-   Never allow tool outputs to bypass normalization
-   Enforce tool limits
-   Always degrade gracefully

This is not just a chatbot.

This is a cinematic conversational intelligence system.

------------------------------------------------------------------------

# Update Log

**2026-03-02 20:35 UTC**

- Upgraded orchestration to Intent-Governed Deterministic Model (v6).
- Added IntentAgent, Guardrails, RoutingMatrix, LayoutPolicyEngine, SessionContext.
- Planner is advisory only; routing matrix is final tool authority.

**2026-03-02 22:45 UTC**

- Added DiscoveryEngine list tools (IMDb trending/top-rated/upcoming).
- Added IMDb personality lookup and Rotten Tomatoes sentiment tool.
- Updated routing and layout policies for list and person intents.

**2026-03-02 23:10 UTC**

- Added EntityResolver for canonicalization and entity typing.
- Enforced award lookup override and download governance policy.
- Added tool grounding retry on missing tool facts.
