# 🎬 FilmDB - Demo: LLM Tool-Calling Schema Documentation

------------------------------------------------------------------------

# 1️⃣ Introduction

This document defines the complete tool-calling schema used in the
FilmDB - Demo backend.

The architecture follows an LLM-first hybrid orchestration model:

-   LLM proposes tool calls
-   Backend validates tool calls
-   Governance layer enforces constraints
-   Tools execute
-   LLM performs final synthesis

This guide explains:

-   Tool definition format
-   Tool call proposal structure
-   Backend validation rules
-   Execution workflow
-   Error handling model
-   Multi-tool calling behavior
-   Governance constraints

------------------------------------------------------------------------

# 2️⃣ Tool Definition Schema

All tools must be defined in a structured registry.

Each tool includes:

``` json
{
  "name": "tool_name",
  "description": "What this tool does",
  "parameters": {
    "type": "object",
    "properties": {
      "title": {
        "type": "string",
        "description": "Movie or person name"
      },
      "region": {
        "type": "string",
        "description": "User region if required"
      }
    },
    "required": ["title"]
  }
}
```

Each tool must have:

-   Clear description
-   Strict parameter definitions
-   Explicit required fields

------------------------------------------------------------------------

# 3️⃣ Available Tools

## IMDb Tool

Purpose: - Fetch metadata - Ratings - Cast - Release year - Poster

Parameters:

``` json
{
  "title": "string"
}
```

------------------------------------------------------------------------

## Wikipedia Tool

Purpose: - Biography - Overview - Filmography background - Historical
context

Parameters:

``` json
{
  "title": "string"
}
```

------------------------------------------------------------------------

## Watchmode Tool

Purpose: - Streaming availability

Parameters:

``` json
{
  "title": "string",
  "region": "string"
}
```

------------------------------------------------------------------------

## Similarity Tool

Purpose: - Content-based recommendations

Parameters:

``` json
{
  "title": "string"
}
```

------------------------------------------------------------------------

## Archive Tool

Purpose: - Legal public domain download

Parameters:

``` json
{
  "title": "string"
}
```

------------------------------------------------------------------------

## Web Search Tool

Purpose: - Latest news - Reviews - Audience sentiment - Box office
updates

Parameters:

``` json
{
  "query": "string"
}
```

------------------------------------------------------------------------

## DiscoveryEngine List Tools

Purpose: - Catalog-level discovery lists

Tools:

- `imdb_trending_tamil` (Trending Tamil movies)
- `imdb_top_rated_english` (Top Rated English movies)
- `imdb_upcoming` (Upcoming releases by country)

Parameters:

``` json
{
  "country": "string"
}
```

Notes:
- `imdb_trending_tamil` and `imdb_top_rated_english` require no parameters.
- `imdb_upcoming` accepts optional `country` (e.g., "IN", "US").

------------------------------------------------------------------------

## IMDb Personality Tool

Purpose: - Person profile, filmography, biography

Parameters:

``` json
{
  "name": "string"
}
```

------------------------------------------------------------------------

## Rotten Tomatoes Reviews Tool

Purpose: - Critics sentiment (score only)

Parameters:

``` json
{
  "title": "string"
}
```

------------------------------------------------------------------------

## 4️ LLM Tool Call Proposal Format

Eg:
Single tool call:

``` json
{
  "tool_call": {
    "name": "watchmode",
    "arguments": {
      "title": "The Godfather",
      "region": "India"
    }
  }
}
```

Multiple tool calls:

``` json
{
  "tool_calls": [
    {
      "name": "imdb",
      "arguments": { "title": "The Godfather" }
    },
    {
      "name": "watchmode",
      "arguments": { "title": "The Godfather", "region": "India" }
    }
  ]
}
```

LLM must not exceed 3 tool calls per proposal.

------------------------------------------------------------------------

## 5️ Backend Validation Rules

When LLM proposes tool calls, backend must:

1. Verify tool exists in registry
2. Validate parameters match schema
3. Check relevance via keyword governance
4. Enforce max 3 tool calls
5. Reject redundant calls
6. Reject irrelevant tools (e.g., streaming when not asked)

If invalid, backend rejects tool call and continues without it.

------------------------------------------------------------------------

## 6️ Tool Governance Constraints

- Maximum 3 tool calls per request
- Tools must match user query intent
- Similarity tool only if recommendations requested
- Archive tool only if download requested
- Wikipedia for descriptive context only
- Web search for freshness or reviews

------------------------------------------------------------------------

# 7️⃣ Execution Workflow

1.  LLM proposes tool calls
2.  Backend validates proposal
3.  Approved tools executed sequentially (simplest implementation)
4.  Tool results normalized
5.  Tool data injected into LLM prompt
6.  LLM generates final response

------------------------------------------------------------------------

# 8️⃣ Error Handling in Tool Calling

Each tool must return:

``` json
{
  "status": "success" | "not_found" | "error",
  "data": {...}
}
```

If tool fails:

-   Retry once
-   If still fails → mark as temporarily unavailable
-   Inject status into LLM context
-   LLM must not hallucinate missing data

------------------------------------------------------------------------

# 9️⃣ Sequential vs Parallel Execution

Recommended for demo: Sequential execution for simplicity.

Optional upgrade: Parallel execution for performance optimization.

LLM does not control parallelism. Backend controls execution strategy.

------------------------------------------------------------------------

# 🔟 Example Full Tool-Calling Flow

User:

"Why is The Godfather considered greatest? Where can I stream it?"

LLM Proposal:

``` json
{
  "tool_calls": [
    { "name": "imdb", "arguments": {"title": "The Godfather"} },
    { "name": "watchmode", "arguments": {"title": "The Godfather", "region": "India"} }
  ]
}
```

Backend:

-   Validates tools
-   Executes IMDb
-   Executes Watchmode
-   Injects structured data
-   Calls LLM for final synthesis

------------------------------------------------------------------------

# 1️⃣1️⃣ Final Design Principles

-   LLM leads reasoning
-   Backend governs execution
-   Tools provide factual grounding
-   Memory remains external
-   Tool usage is constrained but flexible
-   System degrades gracefully

------------------------------------------------------------------------

# 🎯 Closing Note

This schema enables:

-   Intelligent LLM-first orchestration
-   Controlled cost
-   Reduced hallucination risk
-   Clean modular architecture
-   Production-ready extensibility

Build the system with strict schema validation and structured
normalization.

------------------------------------------------------------------------

# Update Log

**2026-02-28 22:40 UTC**

- Similarity tool now supports optional `imdb_id` parameter when RapidAPI similarity is used.

**2026-03-01 20:20 UTC**

- Planner schema standardized on `{ tools_required, confidence, reasoning }`.
- Confidence thresholds expanded to full 4-band logic.
- Enforcement added for factual queries to avoid empty tool lists.

**2026-03-02 20:35 UTC**

- Planner output is advisory; RoutingMatrix determines final tool set.
- filter_tool_calls now only enforces schema/limits (no semantic relevance).

**2026-03-02 21:05 UTC**

- Confidence fallback moved inside RoutingMatrix (no post-matrix tool mutation).

**2026-03-02 22:45 UTC**

- Added DiscoveryEngine list tools and IMDb personality lookup.
- Added Rotten Tomatoes reviews sentiment tool.
