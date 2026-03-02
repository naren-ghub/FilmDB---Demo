# FilmDB Demo -- Architectural Audit & Corrective Implementation Guide

Generated: 2026-03-01 20:58 UTC

------------------------------------------------------------------------

# Executive Summary

This document provides a deep architectural audit of the current FilmDB
backend and defines:

1.  What is structurally incorrect
2.  Why it is incorrect
3.  The exact corrective action
4.  What must NOT be changed
5.  Verification criteria before merge

The goal is to preserve:

-   Intent-Governed orchestration
-   Deterministic structural authority
-   Tool-policy enforcement
-   Controlled LLM usage
-   Async performance and caching integrity

------------------------------------------------------------------------

# SECTION 1 --- CURRENT ARCHITECTURE SNAPSHOT

Pipeline:

User → Pronoun Resolution → IntentAgent → Guardrails → Planner
(Advisory) → RoutingMatrix → Confidence Handling → Schema Validation →
Async Tool Execution → Narrative LLM → LayoutPolicyEngine → Response →
SessionContext Update

The system is no longer Planner-Governed. It is Intent-Governed.

However, certain authority boundaries remain weak.

------------------------------------------------------------------------

# SECTION 2 --- CRITICAL STRUCTURAL ISSUES

------------------------------------------------------------------------

## ISSUE 1 --- ANALYTICAL_EXPLANATION Policy Is Incomplete

Current behavior requires only wikipedia.

Problem:

Analytical explanations require metadata grounding: - Year - Rating -
Director - Cast

These come from imdb.

Architectural risk: Explanations may become shallow and inconsistently
grounded.

### REQUIRED FIX

Update RoutingMatrix:

ANALYTICAL_EXPLANATION: - required: \["imdb"\] - optional:
\["wikipedia", "web_search"\] - forbidden: \["archive"\]

Reason: Metadata must be guaranteed before narrative generation.

------------------------------------------------------------------------

## ISSUE 2 --- Confidence Logic Violates Authority Separation

Current design allows confidence fallback to mutate tool calls after
RoutingMatrix resolution.

Problem:

RoutingMatrix must be final structural authority. No post-matrix
mutation allowed.

Architectural violation: Planner influence reintroduced indirectly.

### REQUIRED FIX

Remove confidence-based mutation after RoutingMatrix.

Instead:

Integrate confidence logic inside RoutingMatrix resolution:

If confidence \< 35: required.add("web_search")

All structural decisions must occur before final tool assembly.

------------------------------------------------------------------------

## ISSUE 3 --- LayoutPolicy Uses Weak Success Detection

Current detection checks existence of data object.

Problem:

Tools may return: status = "not_found" data = {}

Layout may falsely assume availability.

### REQUIRED FIX

Use strict success detection:

has_streaming = ( tool_outputs\["watchmode"\]\["status"\] == "success"
and tool_outputs\["watchmode"\]\["data"\]\["platforms"\] )

Same rule for recommendations.

Layout must depend on SUCCESSFUL data only.

------------------------------------------------------------------------

## ISSUE 4 --- Intent Prompt Integrity

Typographical issues in prompt reduce classification stability.

### REQUIRED FIX

Ensure: - Clean grammar - No malformed tokens - Strict instruction
clarity - No ambiguity

LLM prompts are architectural components, not casual text.

------------------------------------------------------------------------

## ISSUE 5 --- Narrative LLM Has Excess Freedom

Current narrative generation is unconstrained by response_mode.

Risk:

LLM may overemphasize optional sections or distort layout perception.

### RECOMMENDED FIX (Optional but Strong)

Inject response_mode-specific narrative constraints into prompt.

Example:

If response_mode == EXPLANATION_ONLY: - Do not discuss streaming unless
tool data present. - Focus on analytical narrative.

LLM must not influence structural layout.

------------------------------------------------------------------------

# SECTION 3 --- COMPONENTS THAT ARE CORRECT

The following must NOT be altered:

✓ IntentAgent strict JSON classification ✓ Guardrails pre-tool blocking
✓ RoutingMatrix union logic ✓ Async parallel execution (asyncio.gather)
✓ Normalized tool output schema ✓ Caching layer integrity ✓
SessionContext memory ✓ Deterministic LayoutPolicyEngine ✓ Tool cap = 4
✓ Separation of classification / routing / narrative

These form the system's structural backbone.

------------------------------------------------------------------------

# SECTION 4 --- IMPLEMENTATION ORDER

1.  Fix ANALYTICAL_EXPLANATION required tools
2.  Remove post-matrix confidence mutation
3.  Integrate confidence logic inside RoutingMatrix
4.  Strengthen LayoutPolicy success checks
5.  Clean IntentAgent prompt
6.  (Optional) Add narrative-mode constraints

------------------------------------------------------------------------

# SECTION 5 --- ARCHITECTURAL VALIDATION CHECKLIST

Before merging:

□ RoutingMatrix is final authority □ No tool mutation occurs after
matrix resolution □ Layout decisions depend only on successful tool data
□ Guardrails execute before planner □ Planner cannot bypass forbidden
tools □ All tool outputs normalized □ response_mode explicitly set □
SessionContext updates after success only

If any box fails → reject implementation.

------------------------------------------------------------------------

# SECTION 6 --- MATURITY LEVEL AFTER FIXES

After corrections:

System state: Intent-Governed Deterministic Hybrid (Stage 4)

It is:

-   Policy-driven
-   Deterministic in structure
-   LLM-assisted but not LLM-controlled
-   Async-optimized
-   Cache-aware
-   Governed

Not a heuristic chatbot. Not an uncontrolled agent swarm.

A controlled cinematic intelligence engine.

------------------------------------------------------------------------

# END OF DOCUMENT
