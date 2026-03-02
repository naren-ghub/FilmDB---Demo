# FilmDB Architecture Addendum v3

## Entity Resolution, Tool Grounding Enforcement, Governance Rewrite, and Deterministic Award Query Rules

Generated: 2026-03-01 23:36:32

------------------------------------------------------------------------

# 1. EntityResolver Module Specification

## 1.1 Purpose

The EntityResolver module ensures that all entities extracted from user
queries are: - Canonicalized - Type-validated - Normalized before tool
invocation - Safely injected into SessionContext

Pipeline:

User Query\
→ IntentAgent (intent + raw entities)\
→ EntityResolver\
→ Clean Entities\
→ RoutingMatrix\
→ Tool Execution

------------------------------------------------------------------------

## 1.2 Responsibilities

### A. Canonicalization

Examples: - goodfells → Goodfellas\
- god father → The Godfather\
- oscar 2026 → 98th Academy Awards

Implementation Requirements: - Fuzzy matching (RapidFuzz /
Levenshtein) - Alias mapping table - Case normalization - IMDb ID
resolution when possible

------------------------------------------------------------------------

### B. Entity Typing

Entities must be typed as:

-   movie
-   person
-   award_event
-   franchise
-   streaming_platform
-   year
-   country

SessionContext Schema:

{ "last_entity": "...", "entity_type": "...", "last_intent": "..." }

Oscar queries must never be stored as last_person.

------------------------------------------------------------------------

### C. Tool-Ready Argument Construction

Incorrect: "title": "IMDB rating of goodfells"

Correct: "title": "Goodfellas"

Resolver Output Schema:

{ "entity_value": "Goodfellas", "entity_type": "movie", "canonical_id":
"tt0099685" }

------------------------------------------------------------------------

# 2. Tool Grounding Enforcement Contract

## 2.1 Enforcement Rules

Rule 1: If Tool Status = SUCCESS\
- Narrative LLM must use structured tool data\
- Populate structured fields\
- Avoid generic fallback disclaimers

Rule 2: If Tool Status = ERROR\
- LLM may fallback to general knowledge

Rule 3: Structured Field Priority\
For ENTITY_LOOKUP: - title - rating - year - poster_url

If rating exists → must include exact value.

------------------------------------------------------------------------

## 2.2 Prompt Injection Format

Tool data must be injected as:

\[TOOL_DATA\] source: imdb rating: 8.7 year: 1990 \[/TOOL_DATA\]

System must instruct: "You MUST prioritize TOOL_DATA over general
knowledge."

------------------------------------------------------------------------

## 2.3 Failure Enforcement

If tool success AND LLM ignores tool data: - Reject response - Retry in
strict grounding mode

------------------------------------------------------------------------

# 3. Governance Rewrite for DOWNLOAD Intent

## 3.1 Intent Split

DOWNLOAD intent divides into:

-   STREAMING_AVAILABILITY
-   LEGAL_DOWNLOAD
-   ILLEGAL_DOWNLOAD_REQUEST

------------------------------------------------------------------------

## 3.2 Deterministic Policy

If entity_type = movie AND not public domain:

FORBID: - archive tool - direct download links

Instead: - Provide legal streaming platforms - Provide rental/purchase
options

------------------------------------------------------------------------

## 3.3 Public Domain Rule

If release_year \< 1928: Allow archive tool

Else: Disallow archive tool

------------------------------------------------------------------------

## 3.4 RoutingMatrix Update

DOWNLOAD intent:

Required: - streaming_service

Forbidden: - archive (unless public_domain=true)

------------------------------------------------------------------------

# 4. AwardQuery Deterministic Intent Rules

## 4.1 New Intent Category

AWARD_LOOKUP

------------------------------------------------------------------------

## 4.2 Classification Rule

If query contains: - oscar - academy awards - nominations - best picture
nominees

Then: primary_intent = AWARD_LOOKUP\
confidence = 100

------------------------------------------------------------------------

## 4.3 RoutingMatrix for AWARD_LOOKUP

Required: - web_search

Optional: - wikipedia

Forbidden: - imdb (unless specific film mentioned)

------------------------------------------------------------------------

## 4.4 LayoutPolicy Rule

If AWARD_LOOKUP AND film list present: Return RECOMMENDATION_GRID

Else: Return EXPLANATION_ONLY

------------------------------------------------------------------------

# 5. Deterministic Guarantees

After implementation:

-   No malformed tool arguments
-   No ungrounded fallback when tools succeed
-   No illegal download exposure
-   No Oscar query misclassification
-   Stable SessionContext typing
-   Deterministic layout behavior

------------------------------------------------------------------------

# 6. Final System State

FilmDB becomes:

Intent-Governed\
Entity-Normalized\
Tool-Grounded\
Compliance-Enforced\
Deterministic Cinematic Intelligence Engine

------------------------------------------------------------------------

End of Addendum v3
