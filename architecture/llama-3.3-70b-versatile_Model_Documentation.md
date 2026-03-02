# FilmDB - Groq Model Integration Documentation

Model: llama-3.3-70b-versatile\
Provider: Groq\
Last Updated: 2026-02-28 21:58:12 UTC

------------------------------------------------------------------------

## 1. Introduction

This document explains how the Groq model `llama-3.3-70b-versatile` is
integrated into the FilmDB backend.

The system follows an LLM-first, tool-governed hybrid architecture:

-   LLM performs reasoning and synthesis
-   Backend governs tool execution
-   Tools provide factual grounding
-   Memory is stored externally
-   Maximum 3 tool calls per request
-   Async tool execution supported
-   Graceful degradation mandatory

------------------------------------------------------------------------

## 2. Why llama-3.3-70b-versatile

Selected for:

-   Strong multi-step reasoning
-   Better thematic and analytical responses
-   Improved tool-call decisions
-   Lower hallucination risk vs smaller models
-   High-quality structured outputs

------------------------------------------------------------------------

## 3. Environment Configuration

Add to `.env`:

GROQ_API_KEY=your_groq_api_key\
GROQ_MODEL=llama-3.3-70b-versatile

### config.py

``` python
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

settings = Settings()
```

Never hardcode API keys.

------------------------------------------------------------------------

## 4. LLM Phase Strategy

### Phase 1 -- Tool Proposal

-   Temperature: 0.2
-   Deterministic output
-   Returns tool_calls JSON only

### Phase 2 -- Final Synthesis

-   Temperature: 0.6--0.7
-   Full structured prompt
-   Injected tool data
-   Analytical cinematic output

------------------------------------------------------------------------

## 5. Prompt Structure

LLM input must follow strict layering:

SYSTEM\
USER PROFILE\
RECENT CONVERSATION\
TOOL DATA\
USER QUERY

Never inject raw JSON into the model.

------------------------------------------------------------------------

## 6. Tool Calling Rules

LLM may propose:

``` json
{
  "tool_calls": [
    {
      "name": "imdb",
      "arguments": {"title": "The Godfather"}
    }
  ]
}
```

Backend must:

-   Validate tool exists
-   Validate parameters
-   Enforce max 3 tools
-   Reject irrelevant tools
-   Prevent redundant calls

------------------------------------------------------------------------

## 7. Temperature Strategy

Tool Proposal: 0.2\
Final Response: 0.6--0.7

Avoid \>0.8 to reduce hallucination risk.

------------------------------------------------------------------------

## 8. Token Budget Strategy

-   Inject max 8 previous messages
-   Summarize tool outputs
-   Avoid raw review dumps
-   Avoid redundant profile injection

------------------------------------------------------------------------

## 9. Error Handling

If tool returns:

{ "status": "error" \| "not_found" }

System must:

-   Inject structured failure status
-   Prevent hallucination
-   Continue with available data

Example:

Streaming Availability: - Status: Temporarily Unavailable

------------------------------------------------------------------------

## 10. Cost Control

-   Max 3 tool calls
-   Cache metadata (24h)
-   Cache streaming results
-   Avoid redundant calls
-   Monitor token usage

------------------------------------------------------------------------

## 11. Security Rules

-   Never expose GROQ_API_KEY to frontend
-   Never log secrets
-   Backend-only execution
-   Enforce rate limiting

------------------------------------------------------------------------

## Final Philosophy

Use llama-3.3-70b-versatile as primary reasoning engine.

Keep governance strict.\
Keep prompts structured.\
Keep tools normalized.\
Keep memory external.

This ensures demo excellence and scalable design.
