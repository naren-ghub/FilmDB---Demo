# FilmDB Backend -- Critical Architectural Issues & Corrective Action Plan

Generated: 2026-03-01 21:33 UTC

------------------------------------------------------------------------

# Executive Summary

This document records the structural issues identified in the FilmDB
backend after reviewing recent execution logs and behavior.

It provides:

1.  Precise problem identification
2.  Root cause analysis
3.  Architectural reasoning
4.  Deterministic corrective actions
5.  Implementation guidance
6.  Post-fix validation checklist

The objective is to restore full Intent-Governed Deterministic
Architecture compliance.

------------------------------------------------------------------------

# ISSUE 1 --- Dual Tool-Routing Architecture Active

## Problem

Two routing paths are currently co-existing:

A)  Planner-based propose_tools() flow\
B)  IntentAgent + RoutingMatrix deterministic flow

This causes:

-   Tools not executing
-   Web search not triggered for TRENDING queries
-   Inconsistent structural behavior

## Root Cause

Legacy propose_tools() path was not fully removed after migration.

## Architectural Violation

Routing authority must be singular and deterministic.

## Required Fix

REMOVE:

-   GroqClient.propose_tools()
-   \_parse_tool_calls()
-   Any planner-driven primary routing logic

REPLACE WITH:

IntentAgent → RoutingMatrix → Deterministic Tool Construction

All tool calls must be derived strictly from:

-   primary_intent
-   secondary_intents
-   entities
-   RoutingMatrix policy

------------------------------------------------------------------------

# ISSUE 2 --- Confidence Normalization Bug

## Problem

IntentAgent returns:

"confidence": 0.9

Parsed result becomes:

"confidence": 0

This triggers Guardrails block and CLARIFICATION mode.

## Root Cause

Schema expects integer 0--100. Float values were truncated.

## Required Fix

Inside IntentAgent parsing:

    if 0 <= confidence <= 1:
        confidence = confidence * 100

    confidence = int(confidence)

Additionally update prompt to require integer 0--100.

------------------------------------------------------------------------

# ISSUE 3 --- Misclassification of Time-Sensitive Queries

## Problem

Query: "What movies are officially nominated for oscar 2026"

Classified as ANALYTICAL_EXPLANATION.

Correct intent: TRENDING or OFFICIAL.

Impact: Web search became optional instead of required.

## Required Fix

Strengthen IntentAgent examples:

User: what are trending films → TRENDING\
User: oscar nominations 2026 → TRENDING\
User: recent releases this week → TRENDING\
User: who won best picture 2024 → TRENDING

Time-sensitive queries must deterministically trigger web_search.

------------------------------------------------------------------------

# ISSUE 4 --- Tool Data Injection Weakness

## Problem

Even when web_search succeeds, LLM claims lack of real-time data.

## Root Cause

Prompt does not enforce TOOL DATA as authoritative.

## Required Fix

Add to system instructions:

"You MUST rely on TOOL DATA as factual ground truth. If TOOL DATA
exists, do not claim lack of information."

Ensure tool summaries contain concrete bullet facts.

------------------------------------------------------------------------

# ISSUE 5 --- TRENDING Queries Not Triggering Tools

## Problem

Trending queries previously executed zero tools.

## Required Fix

Ensure RoutingMatrix includes:

TRENDING: required = \["web_search"\]

Disallow empty tool_calls for TRENDING intent.

------------------------------------------------------------------------

# IMPLEMENTATION ORDER

1.  Remove propose_tools() architecture
2.  Normalize confidence scale
3.  Strengthen IntentAgent examples
4.  Strengthen TOOL DATA enforcement
5.  Verify TRENDING always triggers web_search

------------------------------------------------------------------------

# POST-FIX VALIDATION CHECKLIST

□ All routing flows use IntentAgent + RoutingMatrix only\
□ No propose_tools() logs appear\
□ Confidence never equals 0 for valid queries\
□ TRENDING queries always execute web_search\
□ Tool execution logs written to DB\
□ LLM does not ignore TOOL DATA\
□ response_mode deterministic

------------------------------------------------------------------------

# Update Log

**2026-03-02 21:18 UTC**

- Implemented confidence normalization (0–1 scaled to 0–100).
- Strengthened IntentAgent examples for TRENDING classification.
- Added system rule to rely on TOOL DATA when available.

------------------------------------------------------------------------

# TARGET STATE

After fixes:

-   Fully Intent-Governed
-   Deterministic routing
-   Confidence-stable
-   Tool-authoritative
-   Architecturally consistent

------------------------------------------------------------------------

# END OF DOCUMENT
