# FilmDB Demo -- Intent-Governed Deterministic Architecture 

## Version

Generated: 2026-03-02\
Purpose: Code-Agent Implementation Guide

------------------------------------------------------------------------

# 1. Executive Summary

This document defines the required architectural changes to upgrade the
current FilmDB Demo backend from a **Planner-Governed Hybrid Model** to
a **Fully Intent-Governed Deterministic Orchestration Model (v6)**.

This document is written for a code agent responsible for implementing
the changes.

The upgrade introduces:

-   IntentAgent (LLM-based classification, strict JSON)
-   Guardrails layer (pre-tool safety)
-   RoutingMatrix (final tool authority)
-   LayoutPolicyEngine (dynamic deterministic layout selection)
-   Minimal SessionContext entity memory
-   Strict separation of structural authority and narrative generation

This upgrade does NOT: - Replace async tool execution - Remove caching -
Remove planner agent - Replace current LLM synthesis - Introduce a
Supervisor Agent

------------------------------------------------------------------------

# 2. Current Architecture (Before Upgrade)

Current orchestration flow:

User\
→ Planner LLM (tool proposal)\
→ Confidence fallback\
→ filter_tool_calls (schema validation)\
→ Async Tool Execution\
→ LLM Final Synthesis\
→ Structured Response

Characteristics:

-   Planner has de facto tool authority.
-   No explicit IntentFamily classification.
-   No RoutingMatrix enforcement.
-   Layout inferred implicitly.
-   No deterministic response_mode contract.

------------------------------------------------------------------------

# 3. Target Architecture (After Upgrade)

Final orchestration flow:

User\
→ SessionContext (pronoun resolution)\
→ IntentAgent (LLM JSON classification)\
→ Guardrails\
→ Planner (advisory only)\
→ RoutingMatrix (final tool authority)\
→ filter_tool_calls (schema validation only)\
→ Async Tool Execution\
→ LayoutPolicyEngine (dynamic deterministic)\
→ Narrative LLM (text only)\
→ SupervisorResponse (mode-bound)

Planner is no longer execution authority.

------------------------------------------------------------------------

# 4. IntentAgent Layer

## 4.1 Purpose

The IntentAgent classifies the user query into structured intent
categories.

It returns STRICT JSON only.

## 4.2 Intent Schema

{ "primary_intent": "INTENT_NAME", "secondary_intents": \[\],
"entities": \[\], "confidence": 0-100 }

## 4.3 Intent Families

-   ENTITY_LOOKUP
-   ANALYTICAL_EXPLANATION
-   FILM_PERSONALITY
-   AVAILABILITY
-   RECOMMENDATION
-   DOWNLOAD
-   REVIEWS
-   TRENDING
-   COMPARISON

## 4.4 Implementation Requirements

-   Temperature ≤ 0.3
-   Strict JSON parsing
-   Fallback to safe default if parsing fails
-   No narrative output
-   No markdown

------------------------------------------------------------------------

# 5. Guardrails Layer

Guardrails execute before tool invocation.

### Conditions

-   confidence \< 30
-   Required entity missing
-   Pronoun-only query without context
-   Unsupported intent

### Behavior

Return clarification response immediately.

No tool execution.\
No narrative LLM call.

------------------------------------------------------------------------

# 6. RoutingMatrix (Tool Authority Layer)

## 6.1 Purpose

RoutingMatrix determines final tool set based on IntentResult.

Planner suggestions are advisory only.

## 6.2 Policy Definition Example

ANALYTICAL_EXPLANATION: required: \["imdb"\] optional: \["wikipedia"\]
forbidden: \["archive"\]

AVAILABILITY: required: \["watchmode"\] optional: \["imdb"\] forbidden:
\[\]

## 6.3 Multi-Intent Resolution

For multiple intents:

Required = union of all required tools\
Forbidden = union of forbidden tools\
Optional = union of optional tools

Forbidden tools removed unless required by another intent.

------------------------------------------------------------------------

# 7. Schema Validation (Existing Layer)

Retain filter_tool_calls() for:

-   Tool existence validation
-   Required argument enforcement
-   Duplicate prevention
-   Max tool cap (4)

Remove keyword-based semantic enforcement.

------------------------------------------------------------------------

# 8. Async Tool Execution

No structural changes required.

Must retain:

-   asyncio.gather execution
-   Timeout control
-   One retry on failure
-   Normalized tool output: { "status": "success\|not_found\|error",
    "data": {...} }
-   Caching updates
-   Tool logging

------------------------------------------------------------------------

# 9. LayoutPolicyEngine (Dynamic Deterministic)

## 9.1 Purpose

Select response_mode deterministically using:

-   primary_intent
-   secondary_intents
-   tool_outputs
-   data completeness flags

## 9.2 Response Modes

-   FULL_CARD
-   MINIMAL_CARD
-   EXPLANATION_ONLY
-   EXPLANATION_PLUS_AVAILABILITY
-   AVAILABILITY_FOCUS
-   RECOMMENDATION_GRID
-   CLARIFICATION

## 9.3 Deterministic Rule Example
1
If primary == ANALYTICAL_EXPLANATION: if streaming data present: return
EXPLANATION_PLUS_AVAILABILITY else: return EXPLANATION_ONLY

Given same inputs → same output.

No LLM involvement.

------------------------------------------------------------------------

# 10. Narrative LLM Responsibilities

LLM now only generates:

-   text_response (narrative explanation)

It must NOT:

-   Select layout
-   Add streaming info
-   Modify response_mode
-   Invent metadata

Structural authority remains backend.

------------------------------------------------------------------------

# 11. SessionContext (Minimal Entity Memory)

## 11.1 Database Table

session_id (PK)\
last_movie\
last_person\
last_intent\
updated_at

## 11.2 Behavior

Before IntentAgent:

-   Resolve pronouns using last_movie / last_person.

After successful tool execution:

-   Update context using grounded entity.

No full conversation injection into LLM.

------------------------------------------------------------------------

# 12. SupervisorResponse Contract

Final API response must include:

{ "response_mode": "...", "text_response": "...", "poster_url": "...",
"streaming": \[...\], "recommendations": \[...\], "download_link":
"...", "sources": \[...\] }

UI renders strictly by response_mode.

------------------------------------------------------------------------

# 13. Implementation Order

1.  Implement IntentAgent
2.  Add Guardrails layer
3.  Implement RoutingMatrix
4.  Modify ConversationEngine flow
5.  Implement LayoutPolicyEngine
6.  Integrate SessionContext
7.  Remove planner dominance logic
8.  Validate async execution stability

------------------------------------------------------------------------

# 14. Non-Goals

Do NOT:

-   Introduce Supervisor Agent
-   Let LLM select layout
-   Allow planner to override RoutingMatrix
-   Inject full DB state into LLM
-   Reintroduce keyword-based governance

------------------------------------------------------------------------

# 15. Final Outcome

After upgrade:

-   Intent governs tool routing
-   RoutingMatrix enforces policy
-   Layout is deterministic and dynamic
-   LLM is narrative-only
-   UI is mode-bound
-   Tool usage is disciplined
-   Multi-intent queries are stable
-   Structural hallucination risk minimized

This completes the transition from Planner-Governed Hybrid to
Intent-Governed Deterministic Orchestration (v6).
