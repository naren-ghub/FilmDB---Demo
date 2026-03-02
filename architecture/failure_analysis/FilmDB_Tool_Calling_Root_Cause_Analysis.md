# 🎬 FilmDB - Tool Calling Failure: Root Cause Analysis & Fix Plan

**Generated:** 2026-03-01 15:15:24 UTC

------------------------------------------------------------------------

## 1️⃣ Executive Summary

The FilmDB system follows a Planner-Agent-based hybrid architecture.
However, tool calling has been failing due to implementation-level
contradictions.

This document explains:

-   What the real problems are
-   Why they arise
-   How they break tool execution
-   The exact fixes required
-   What changes must be implemented immediately

------------------------------------------------------------------------

# 2️⃣ Core Problem Overview

Although the architecture upgrade introduced a Planner Agent, the actual
implementation contains a **schema mismatch and execution flow errors**.

As a result:

-   Planner returns structured JSON
-   Groq client fails to parse it
-   Conversation engine receives empty tool list
-   No tools execute
-   Final LLM answers from memory
-   Responses become shallow and ungrounded

------------------------------------------------------------------------

# 3️⃣ Critical Problem #1: Planner JSON Schema Mismatch

## What Happens

Planner returns:

``` json
{
  "tools_required": [...],
  "confidence": 82,
  "reasoning": "..."
}
```

But the Groq client only parses:

``` json
{ "tool_calls": [...] }
```

## Why It Arises

The `GroqClient._parse_tool_calls()` method only checks for:

-   "tool_calls"
-   "tool_call"

It never checks for:

-   "tools_required"
-   "confidence"

## Result

Planner output is discarded. Engine interprets it as empty tool
proposal. No tools execute.

------------------------------------------------------------------------

## ✅ Fix

Modify `GroqClient.propose_tools()` to:

1.  Parse full JSON
2.  Detect "tools_required"
3.  Return structured planner object
4.  Provide fallback structure if parsing fails

Without this fix, Planner architecture cannot function.

------------------------------------------------------------------------

# 4️⃣ Critical Problem #2: Double SYSTEM Prompt Injection

## What Happens

Conversation engine builds a structured prompt that already includes:

    SYSTEM:
    ...

Then `generate_response()` injects another system message.

This results in nested system instructions.

## Why It Arises

The LLM call format mixes: - Full structured prompt - Separate system
role message

## Result

-   Prompt contamination
-   Reduced grounding quality
-   Inconsistent behavior

------------------------------------------------------------------------

## ✅ Fix

Either:

-   Remove system injection in `generate_response()`
-   Or refactor to pass full message array cleanly

Avoid duplicating SYSTEM sections.

------------------------------------------------------------------------

# 5️⃣ Architectural Inconsistency: Confidence Logic

## Intended Design

Confidence thresholds:

  Confidence   Action
  ------------ -------------------------
  70--100      Execute as-is
  50--69       Execute normally
  35--49       Force web_search
  0--34        Force web_search + imdb

## Current Implementation

Only adds web_search if confidence \< 50.

## Problem

The lowest confidence band (0--34) is not handled properly.

## Fix

Implement full threshold logic exactly as defined in upgrade document.

------------------------------------------------------------------------

# 6️⃣ The "Lazy Planner" Loophole

## What Happens

Planner is allowed to return:

``` json
{ "tools_required": [] }
```

This allows model to answer from memory.

## Why It Arises

Planner prompt includes:

"If no tools are needed, return empty tools_required array."

Large models prefer memory-based answers unless forced.

## Result

-   No tool calls
-   No grounding
-   Outdated or hallucinated data

------------------------------------------------------------------------

## ✅ Fix

Strengthen planner instructions:

-   Require at least one tool for factual movie queries
-   Lower confidence automatically for freshness-based queries
-   Add forced fallback enforcement layer

------------------------------------------------------------------------

# 7️⃣ What Is NOT The Problem

The issue is NOT caused by:

-   Groq model capability
-   Async execution
-   Database schema
-   Cache layer
-   Tool services implementation

Those components are correctly structured.

The failure is purely orchestration-layer mismatch.

------------------------------------------------------------------------

# 8️⃣ Full Fix Checklist

## Mandatory Fixes

-   Update GroqClient JSON parsing logic
-   Remove double SYSTEM injection
-   Implement full confidence threshold logic
-   Strengthen planner enforcement rules

## Recommended Enhancements

-   Add forced fallback layer after planner
-   Log planner JSON before filtering
-   Log confidence values
-   Validate tool proposal success rate

------------------------------------------------------------------------

# 9️⃣ Expected Outcome After Fix

After implementing corrections:

-   Planner JSON parsed correctly
-   Confidence logic activates
-   Tools execute consistently
-   Tool logs populate
-   Structured fields populate (poster, streaming, sources)
-   Responses become grounded and professional

------------------------------------------------------------------------

# 🔟 Final Architectural Insight

The system design itself is strong.

The failure arose from:

-   Schema mismatch
-   Prompt layering mistake
-   Incomplete confidence implementation
-   Planner escape route

Once these are fixed, the FilmDB system will operate as a properly
governed, LLM-first cinematic intelligence engine.

------------------------------------------------------------------------

**End of Document**
