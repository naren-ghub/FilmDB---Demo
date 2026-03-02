## Plan Proposal — 2026-02-28

# FilmDB Demo — Backend Skeleton Implementation Plan (Groq + SQLite/SQLAlchemy)

**Summary**
We will implement a working backend skeleton that follows the architecture docs: FastAPI API layer, conversation engine, governance, prompt builder, tool registry, normalized tool stubs, Groq LLM integration (two-phase), and a SQLite + SQLAlchemy data layer for sessions/profiles/caches/logs. Real tool integrations are stubbed with deterministic placeholder responses.

---

## Scope and Success Criteria
- Deliver a runnable FastAPI server with `/chat` endpoint.
- Conversation engine enforces max 3 tool calls, validates schema and relevance, executes tools asynchronously, builds structured prompt, and calls Groq for final synthesis.
- SQLite database stores users, profiles, sessions, messages, tool logs, and caches.
- All tool responses normalized as `{status, data}`.
- No real external tool APIs (IMDb/Wikipedia/etc.) yet; stubs return structured placeholder data.
- Minimal but structured logging; no secrets leaked.

---

## Architecture Alignment (Constraints)
- LLM-first reasoning; backend governs tool execution.
- Tool calls validated against registry and schema.
- Max 3 tool calls per request.
- Last 8 messages injected to LLM.
- One retry on tool failure.
- Graceful degradation with structured status in prompt.
- Prompt layering: SYSTEM → USER PROFILE → RECENT CONVERSATION → TOOL DATA → USER QUERY.

---

## Implementation Steps

### 1. Project Structure
Create directories and modules (per docs):
- `backend/app/main.py` — FastAPI app, `/chat` endpoint.
- `backend/app/config.py` — `.env` loader, Groq settings.
- `backend/app/conversation_engine.py` — orchestrator.
- `backend/app/governance.py` — tool validation, limits.
- `backend/app/llm/groq_client.py` — Groq client wrapper.
- `backend/app/services/*.py` — tool stubs (imdb, wikipedia, watchmode, similarity, archive, web_search).
- `backend/app/db/models.py` — SQLAlchemy models.
- `backend/app/db/session_store.py` — session + message queries.
- `backend/app/db/cache_layer.py` — cache get/set with TTL checks.
- `backend/app/utils/prompt_builder.py` — structured prompt.
- `backend/app/utils/tool_formatter.py` — normalize tool outputs.
- `backend/requirements.txt` — FastAPI, SQLAlchemy, groq client, dotenv, pydantic, asyncio tooling.

### 2. Configuration
- `.env` usage: `GROQ_API_KEY`, `GROQ_MODEL` (default `llama-3.3-70b-versatile`), `DATABASE_URL=sqlite:///./FilmDB_Demo.db`.
- `config.py` loads env via `dotenv`.

### 3. Database Layer
- SQLAlchemy models for:
  - `users`, `user_profiles`, `sessions`, `messages`, `tool_calls`
  - `movie_metadata_cache`, `streaming_cache`, `similarity_cache`
- Provide CRUD helpers:
  - `get_or_create_user(user_id)`
  - `get_or_create_session(session_id, user_id)`
  - `fetch_last_messages(session_id, limit=8)`
  - `store_message(session_id, role, content, token_count)`
  - cache read/write with `cached_at` timestamp

### 4. Tool Registry + Governance
- Define tool registry with JSON schema for parameters.
- Governance logic:
  - Validate tool exists and required params present.
  - Relevance rules:
    - similarity only when recs requested
    - archive only when download requested
    - watchmode only when streaming requested
    - web_search only when freshness/reviews requested
  - Enforce max 3 tool calls.
  - Drop duplicates by tool name + params.
  - One retry on failure.

### 5. Tool Stubs (Stateless)
Each tool returns `{status, data}`; no external calls yet.
- imdb: return fake metadata structure.
- wikipedia: return short overview placeholder.
- watchmode: return empty list + status `not_found` unless region provided.
- similarity: return 3–5 placeholder recs.
- archive: return `not_found`.
- web_search: return brief placeholder.

### 6. LLM Integration (Groq)
- Implement Groq client:
  - Phase 1 (tool proposal): temperature 0.2, JSON-only tool_calls response.
  - Phase 2 (final synthesis): temperature 0.6–0.7, full prompt.
- Validate tool proposal JSON (fallback to no tools if invalid).

### 7. Prompt Builder
Assemble prompt segments:
- SYSTEM: static instructions.
- USER PROFILE: only relevant fields if present.
- RECENT CONVERSATION: last 8 messages.
- TOOL DATA: normalized summaries (never raw JSON).
- USER QUERY: current message.

### 8. API Layer
- `/chat` POST accepts `{session_id, user_id, message}`.
- Calls conversation engine and returns:
  ```json
  {
    "text_response": "...",
    "poster_url": "...",
    "streaming": [...],
    "recommendations": [...],
    "download_link": "...",
    "sources": [...]
  }
  ```
- Always return a well-formed response even if tools fail.

---

## Public APIs / Interfaces
- New HTTP endpoint: `POST /chat` (FastAPI).
- LLM tool proposal JSON schema enforced by governance.
- Internal interface `ConversationEngine.run(session_id, user_id, message)` → response dict.

---

## Tests and Scenarios
- Unit tests:
  - Governance: max 3 tools, invalid tool rejected, relevance filters.
  - Tool formatter: normalized `{status, data}` shape.
  - Prompt builder: ordered sections, no raw JSON.
- Integration tests:
  - `/chat` with no tool calls → LLM final response.
  - `/chat` with tool proposal → normalized tool data included.
  - Tool failure → graceful degradation, no crash.
- Smoke test:
  - Run server and make a single `/chat` call.

---

## Assumptions and Defaults
- Use SQLite + SQLAlchemy.
- Groq is the only LLM provider for now.
- Tool services are stubbed (no real external API calls).
- No frontend changes required for this phase.

---

## Acceptance Criteria
- `uvicorn app.main:app --reload` starts successfully.
- `/chat` returns structured JSON response.
- Tool governance enforces limits and relevance.
- Database stores messages and tool logs.
- LLM calls are two-phase with specified temperatures.

## Plan Proposal — 2026-03-01

# FilmDB Tool-Calling Fixes Plan (Planner Schema + Confidence + Enforcement)

**Summary**
Implement fixes to make tool calling reliable: parse `tools_required` + `confidence` planner schema, remove double SYSTEM injection, implement full confidence thresholds, and enforce tool usage for factual queries. Add planner observability and update architecture docs.

---

## Scope
- Orchestration changes in `backend/app/conversation_engine.py` and `backend/app/llm/groq_client.py`
- Logging and governance adjustments
- Architecture doc updates

---

## Key Changes
- **Planner schema**: parse `{ tools_required, confidence, reasoning }` as source of truth.
- **Confidence thresholds**: 70–100 and 50–69 execute as-is; 35–49 force `web_search`; 0–34 force `web_search` + `imdb`.
- **Planner strictness**: enforce tool usage for factual queries even if planner returns empty.
- **System prompt**: remove double SYSTEM injection by sending only structured prompt to LLM for final response.

---

## Tests
- Planner parsing (valid + legacy fallback)
- Confidence fallback injection
- Tool enforcement on factual queries
- Smoke: tool logs populated for trending/streaming queries

---

## Acceptance Criteria
- Tools execute for factual queries
- Confidence fallback works for low confidence
- No duplicate SYSTEM instructions
- Tool logs populate; structured response fields fill when tools run

## Implementation Log — 2026-03-02

# FilmDB v6 Intent-Governed Deterministic Upgrade (Implemented)

**Summary**
Upgraded orchestration to v6 as specified in `architecture/architectural_changes/FilmDB_Architecture_Upgrade.md`. Added IntentAgent, Guardrails, RoutingMatrix, LayoutPolicyEngine, and SessionContext with SQLite persistence. Planner is now advisory; routing matrix is final tool authority. LLM now generates narrative only and uses structured prompt without double SYSTEM injection.

---

## New Modules
- `backend/app/intent_agent.py`
- `backend/app/guardrails.py`
- `backend/app/routing_matrix.py`
- `backend/app/layout_policy.py`

---

## Data Model
- Added `SessionContext` table in `backend/app/db/models.py`
- Added CRUD helpers in `backend/app/db/session_store.py`

---

## Orchestration Changes
- IntentAgent classification before planner
- Guardrails block low-confidence / pronoun-only requests
- RoutingMatrix selects tool set; planner only advisory
- LayoutPolicyEngine sets `response_mode` deterministically
- SessionContext used for pronoun resolution and entity memory

---

## Docs Updated
- `architecture/architecture_overview.md`
- `architecture/LLM_Tool_Calling_Schema_Documentation.md`
- `architecture/Conversation_Engine_Documentation.md`

--------------------------------------------------------------------

## Plan Proposal — 2026-03-02

# FilmDB DiscoveryEngine + Personality Intelligence Integration Plan

**Summary**
Implement the DiscoveryEngine list endpoints (Trending Tamil, Top Rated English, Upcoming by country), IMDb personality lookup, and Rotten Tomatoes sentiment tool. Update intent taxonomy, routing matrix, layout policy, tool registry, and conversation orchestration to support catalog-level and person-level queries. Keep existing LLM report flow intact.

---

## Scope
- New services:
  - DiscoveryEngine list endpoints (IMDb)
  - IMDb personality endpoint
  - Rotten Tomatoes reviews sentiment
- Tool registry + governance updates
- IntentAgent taxonomy expansion
- RoutingMatrix + LayoutPolicyEngine updates
- ConversationEngine dispatch & response formatting updates

---

## Implementation Steps
1. Review current services, intent taxonomy, routing matrix, layout policy, and cache/tool flow to find integration points.
2. Implement new services and normalize outputs (movies list, person profile, reviews sentiment).
3. Extend IntentAgent taxonomy and update routing/layout policies for list and person intents.
4. Wire new tools into ConversationEngine tool call building/dispatch and response mapping.
5. Update docs/agent.md log; run tests if feasible.

---

## Acceptance Criteria
- TRENDING/UPCOMING/TOP_RATED requests call DiscoveryEngine tools and return normalized lists.
- PERSON_LOOKUP requests call IMDb personality tool and return normalized profile data.
- REVIEWS intent uses Rotten Tomatoes sentiment tool.
- LayoutPolicyEngine returns RECOMMENDATION_GRID for list intents and FULL_CARD for person lookup.
- No regressions in existing tool flows or llm_report logging.

## Implementation Log — 2026-03-02

**DiscoveryEngine + Personality Integration**
- Added DiscoveryEngine list service with IMDb trending/top-rated/upcoming endpoints.
- Added IMDb personality service (name lookup + profile fetch).
- Added Rotten Tomatoes reviews sentiment service (score + sentiment).
- Extended tool registry, routing matrix, intent taxonomy, and layout policy for new intents.
- Wired new tools into ConversationEngine (tool calls, dispatch, response mapping).
- Updated tool summary formatting and architecture docs.

**Addendum v3: Entity Resolver + Governance + Award Rules**
- Added EntityResolver for canonicalization, typing, and public-domain heuristics.
- Added AWARD_LOOKUP intent override and download intent splitting (legal vs illegal).
- Enforced download policy to forbid archive unless public domain.
- Added tool grounding retry when IMDb data is ignored.
- Extended SessionContext schema with `last_entity` and `entity_type`.
