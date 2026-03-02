# 🎬 FilmDB - Conversation Engine Documentation

*Last Updated: 2026-02-28 19:39:33 UTC*

------------------------------------------------------------------------

## 1️⃣ Introduction

The Conversation Engine is the **core orchestration layer** of the
FilmDB system.

It follows an **LLM-first, tool-governed hybrid architecture**, where:

-   The LLM handles reasoning and synthesis
-   The backend governs tool execution
-   Tools provide factual grounding
-   Memory is stored externally
-   Maximum 3 tool calls per request
-   Async parallel execution is supported

------------------------------------------------------------------------

## 2️⃣ Architectural Philosophy

### Core Principles

-   LLM is the reasoning engine
-   Backend is the authority layer
-   Tools are stateless
-   Memory is external
-   Governance prevents over-calling
-   Graceful degradation is mandatory

The system is not a multi-agent system.\
It is a single, orchestrated conversational intelligence pipeline.

------------------------------------------------------------------------

## 3️⃣ High-Level Flow

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

------------------------------------------------------------------------

## 4️⃣ Core Responsibilities

The Conversation Engine is responsible for:

1.  Loading session memory (last 8 messages)
2.  Loading user profile
3.  Handling LLM tool proposals
4.  Validating tools against registry
5.  Enforcing max 3 tool calls
6.  Executing tools asynchronously
7.  Normalizing tool responses
8.  Constructing structured LLM prompt
9.  Calling LLM for final synthesis
10. Storing conversation in database
11. Returning structured API response

------------------------------------------------------------------------

## 5️⃣ Tool Governance Layer

### Validation Rules

-   Tool must exist in registry
-   Parameters must match schema
-   Tool must match query relevance
-   Maximum 3 tool calls per request
-   Similarity tool only if recommendations requested
-   Archive tool only if download requested
-   Retry failed tools once

------------------------------------------------------------------------

## 6️⃣ Async Parallel Execution

Tool calls are executed in parallel using asyncio:

``` python
results = await asyncio.gather(*tasks, return_exceptions=True)
```

Benefits:

-   Reduced latency
-   Better UX
-   Independent tool execution
-   No inter-tool dependency

LLM does not control parallelism. Backend controls execution strategy.

------------------------------------------------------------------------

## 7️⃣ Tool Output Normalization

All tools must return standardized output:

``` json
{
  "status": "success" | "not_found" | "error",
  "data": {...}
}
```

Raw API responses must never be injected directly into the LLM prompt.

------------------------------------------------------------------------

## 8️⃣ Prompt Construction Template

Final LLM input structure:

    SYSTEM:
    [Static instructions]

    USER PROFILE:
    [Injected selectively]

    RECENT CONVERSATION:
    [Last 8 exchanges]

    TOOL DATA:
    [Structured summaries]

    USER QUERY:
    [Current user message]

Never inject raw JSON.

------------------------------------------------------------------------

## 9️⃣ Error Handling Strategy

Graceful degradation is mandatory.

If a tool fails:

-   Retry once
-   If still fails → mark as "temporarily unavailable"
-   Inject status into prompt
-   LLM must not hallucinate missing data

The conversation must continue even if one tool fails.

------------------------------------------------------------------------

## 🔟 Database Interactions

The Conversation Engine interacts with:

-   Sessions table (load/store messages)
-   User profile table (personalization)
-   Tool logs table (observability)
-   Cache tables (cost reduction)

The database is the system's memory authority.

------------------------------------------------------------------------

## 1️⃣1️⃣ Cost Control Strategy

-   Max 3 tool calls per request
-   Cache metadata for 24 hours
-   Cache streaming results
-   Avoid redundant calls within session
-   Log tool usage for monitoring

------------------------------------------------------------------------

## 1️⃣2️⃣ Response Output Schema

The engine returns structured JSON:

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

Frontend controls layout.\
LLM controls language.

------------------------------------------------------------------------

## 1️⃣3️⃣ Scalability Considerations

For demo:

-   SQLite is sufficient
-   Async execution improves performance

For production:

-   Move to PostgreSQL
-   Add Redis caching
-   Add rate limiting
-   Add structured logging & monitoring

------------------------------------------------------------------------

## 🎯 Final Design Philosophy

The Conversation Engine is:

-   LLM-first
-   Tool-governed
-   Async-capable
-   Cost-aware
-   Memory-backed
-   Modular
-   Graceful under failure

It balances creative intelligence with controlled execution.

------------------------------------------------------------------------

# 📌 Closing Note

The Conversation Engine is the backbone of the FilmDB cinematic
intelligence system.

Keep orchestration clean.\
Keep tools isolated.\
Keep prompts structured.\
Keep governance strict but lightweight.

This design ensures both demo-readiness and production scalability.

------------------------------------------------------------------------

# Update Log

**2026-03-01 20:20 UTC**

- Adopted planner schema with `tools_required`, `confidence`, and `reasoning`.
- Implemented full confidence fallback bands (web_search / imdb injection).
- Added enforcement to prevent empty tool lists on factual queries.
- Removed double SYSTEM injection by sending only structured prompt to LLM.

**2026-03-02 20:35 UTC**

- Inserted IntentAgent classification before planner.
- Added Guardrails for low-confidence or missing-entity queries.
- RoutingMatrix now final tool authority; planner is advisory only.
- LayoutPolicyEngine determines response_mode deterministically.
- SessionContext used for pronoun resolution (minimal entity memory).

**2026-03-02 21:05 UTC**

- Moved confidence-based web_search injection into RoutingMatrix (no post-matrix mutation).
- Tightened LayoutPolicy success checks to require tool status == success and non-empty data.
- Cleaned IntentAgent prompt grammar for stability.
