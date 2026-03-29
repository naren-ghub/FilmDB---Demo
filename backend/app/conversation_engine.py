import asyncio
import os
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from app.config import settings
from app.db.models import SessionLocal
from app.db.cache_layer import (
    get_metadata_cache,
    get_streaming_cache,
    set_metadata_cache,
    set_streaming_cache,
)
from app.db.session_store import (
    fetch_last_messages,
    get_or_create_session,
    get_or_create_user,
    get_session_context,
    get_user_profile,
    log_request,
    store_message,
    store_tool_call,
    upsert_session_context,
)
from app.governance import filter_tool_calls
from app.guardrails import should_block
from app.entity_resolver import EntityResolver
from app.intent.hybrid_intent_classifier import HybridIntentClassifier  # kept for rollback
from app.intent.unified_intent_tool_agent import UnifiedIntentToolAgent
from app.intent.domain_classifier import DomainClassifier
from app.llm.groq_client import GroqClient  # kept for shadow mode / fallback
from app.layout_policy import select_response_mode, select_layout_segments
from app.utils.prompt_builder import build_prompt
from app.utils.tool_formatter import summarize_all
from app import services
from app.services.kb_service import (
    recommendation_engine,
    oscar_award,
)
from app.entity_memory import EntityMemory
from app.query_category import (
    classify_query_category,
    generate_followups,
    deserialize_categories,
)


SYSTEM_INSTRUCTIONS = """
You are FilmDB — a cinematic intelligence assistant with the depth of a film studies scholar and the warmth of a passionate cinephile.

VOICE & APPROACH:
- Write like a knowledgeable film scholar who speaks accessibly, not academically.
- Lead with insight, not summary. Open with what makes the subject compelling.
- When reference data is available, synthesize it into your analysis — cite ideas, weave in theoretical frameworks, and ground your response in the material.
- Balance factual precision (ratings, years, cast) with analytical depth (themes, aesthetic choices, cultural significance).

RESPONSE FORMAT BY QUERY TYPE:
| Query Type                                      | Format & Length                                                                                      |
|-------------------------------------------------|------------------------------------------------------------------------------------------------------|
| ENTITY_LOOKUP / PERSON_LOOKUP                   | Compelling one-liner. Weave metadata naturally into prose. Under 200 words unless depth is requested |
| FILM_ANALYSIS / VISUAL_ANALYSIS / DIRECTOR_ANALYSIS | Flowing prose, occasional bullets. No "Conclusion" section. 400–600 words                       |
| CONCEPTUAL_EXPLANATION / MOVEMENT_OVERVIEW / HISTORICAL_CONTEXT | Rich layered explanation, reference specific films. 300–500 words               |
| RECOMMENDATION / TOP_RATED / TRENDING           | Curated list. 2–3 sentence rationale per film. No essay structure.                                   |
| COMPARISON                                      | Narrative "versus" style. End with a nuanced verdict, not "both are great".                          |
| STREAMING_AVAILABILITY                          | Direct and concise. List platforms with pricing if known. Under 150 words.                           |
| DOWNLOAD / LEGAL_DOWNLOAD                       | Provide link if archive data exists. If not found: "Not available on legal download sites but may be streamable on [platforms]." Never lecture. |
| BOT_INTERACTION                                 | 1–2 warm sentences. Suggest 2–3 specific capabilities. Under 50 words.                               |
| FILMOGRAPHY                                     | List films with year. Brief note on significance for standout works only — don't describe every film. |
| AWARD_LOOKUP                                    | Lead with total wins/nominations. List key categories. Keep under 200 words.                         |

STRUCTURE RULES:
- Open with a catchy header related to the query.
- NEVER close with "## Conclusion" or a paragraph that merely restates the response.
- Use specific, descriptive section headers when needed (e.g., "Kubrick's Visual Obsessions" not "Visual Style").
- Do NOT repeat information already present in the conversation history.

SOURCE DISCIPLINE:
- [VERIFIED FACTS] = structured external data (IMDb, TMDB, awards, streaming). Always use these exact values. Never invent or contradict ratings, years, cast, or platform data from this section.
- [CURATED KNOWLEDGE] = scholarly RAG content (plots, film essays, scripts). Synthesize into your analysis — cite ideas, weave in frameworks, and ground your response in this material.
- [SUPPLEMENTARY] = Wikipedia summaries and web articles. Use selectively — only when it adds unique value. You may disregard it if it is not relevant.
- You MAY draw on your own knowledge to supplement any tier, but never to CONTRADICT [VERIFIED FACTS].
- Never use labels like "TOOL DATA", "reference data", "VERIFIED FACTS", or any internal system terms in your response.

WHEN SEARCH STATUS INDICATES NO RESULTS:
- You must answer the user's query seamlessly using your internal knowledge.
- DO NOT mention that the entity is not in the database.
- DO NOT explicitly state that your knowledge is unverified or from general knowledge.
- CRITICAL: Even if the database fails, YOU ARE A CINEMA EXPERT. ALWAYS interpret ambiguous queries (like "Oppenheimer" or "Jobs") as referring to movies, actors, or directors — NOT general history or generic science.
- DO NOT hallucinate, invent, or guess precise ratings, release dates, streaming platforms, or box office numbers. Keep the summary qualitative and factual based on your training.
- If the entity is entirely outside your training knowledge (e.g. a very recent film), gracefully admit you don't know it instead of inventing a character or plot.

STRICT TEMPORAL CONSISTENCY:
- Pay strict attention to the current date/year provided in the TEMPORAL CONTEXT.
- If today's year is 2026, you MUST NOT refer to a film from 2023 or 2024 as "upcoming" or "highly anticipated" just because it was upcoming in your pre-training data. Re-align your internal knowledge to match the current date.

FOLLOW-UP SUGGESTIONS (when instructed):
- If FOLLOW-UP SUGGESTIONS appear in the dynamic instructions, add exactly 1 brief, natural sentence at the very end of your response.
- Example: "If you're curious, I can also explore its themes and cinematography."
- Never add follow-up suggestions unless explicitly instructed — do not manufacture them.
"""



def _resolve_tool_group(tool_names: list[str]) -> str:
    """Legacy helper: previously used to categorize tools into buckets for metadata tracking."""
    return "unified_agent"


class ConversationEngine:
    # Feature flag — set USE_UNIFIED_AGENT=false to fall back to old Tier-2
    _USE_UNIFIED_AGENT: bool = True

    def __init__(self) -> None:
        self.llm = GroqClient(api_key=settings.GROQ_API_KEY)
        
        # Dedicated key for intent classification to prevent rate limit collisions
        intent_key = settings.GROQ_INTENT_API_KEY or settings.GROQ_API_KEY
        self.intent_client = GroqClient(api_key=intent_key)

        # Use a dedicated key for response generation if provided, else reuse the main key
        response_key = settings.GROQ_RESPONSE_API_KEY or settings.GROQ_API_KEY
        self.response_client = GroqClient(api_key=response_key)

        # Tier-2 — new unified agent (replaces HybridIntentClassifier Tier-2 + tool_selector)
        self.unified_agent  = UnifiedIntentToolAgent()
        self.domain_clf     = DomainClassifier.get_instance()

        # Legacy Tier-2 — kept for rollback / shadow comparison
        self.hybrid_clf    = HybridIntentClassifier(self.llm)

        self.entity_resolver = EntityResolver()
        self.logger = logging.getLogger(__name__)

    async def run(self, session_id: str, user_id: str, message: str) -> Dict[str, Any]:
        response, _trace = await self._run_internal(session_id, user_id, message)
        return response

    async def run_with_trace(
        self, session_id: str, user_id: str, message: str
    ) -> tuple[Dict[str, Any], dict[str, Any]]:
        return await self._run_internal(session_id, user_id, message)

    async def _run_internal(
        self, session_id: str, user_id: str, message: str
    ) -> tuple[Dict[str, Any], dict[str, Any]]:
        db = SessionLocal()
        start_llm_calls = (
            getattr(self.llm, "total_calls", 0) + 
            getattr(self.intent_client, "total_calls", 0) + 
            getattr(self.response_client, "total_calls", 0)
        )
        trace: dict[str, Any] = {
            "session_id": session_id,
            "user_id": user_id,
            "message": message,
            "_start_time": time.time(),
        }
        try:
            get_or_create_user(db, user_id)
            get_or_create_session(db, session_id, user_id)
            profile = get_user_profile(db, user_id)
            session_ctx = get_session_context(db, session_id)
            resolved_message = self._resolve_pronouns(message, session_ctx)
            trace["session_context_before"] = (
                {
                    "last_movie": session_ctx.last_movie,
                    "last_person": session_ctx.last_person,
                    "last_entity": getattr(session_ctx, "last_entity", None),
                    "entity_type": getattr(session_ctx, "entity_type", None),
                    "last_intent": session_ctx.last_intent,
                }
                if session_ctx
                else None
            )
            trace["resolved_message"] = resolved_message

            # ── Tier 1: Domain classification (0 tokens, ~2ms) ───────────────
            domain_result = self.domain_clf.classify(resolved_message)
            self.logger.info(
                "Tier-1 domain: %s score=%.3f mode=%s",
                domain_result.domain, domain_result.score, domain_result.mode,
            )

            # ── Tier 2: Unified intent + tool selection (1 LLM call) ─────────
            if self._USE_UNIFIED_AGENT:
                agent_result = self.unified_agent.classify_and_select(
                    resolved_message, domain_result, self.intent_client
                )
                # Shape agent output into the existing `intent` dict contract
                # (all downstream code uses intent.get("primary_intent") etc.)
                intent = {
                    "primary_intent":    agent_result.get("primary_intent", "ENTITY_LOOKUP"),
                    "secondary_intents": agent_result.get("secondary_intents", []),
                    "entities":          agent_result.get("entities", []),
                    "confidence":        agent_result.get("confidence", 70),
                    "domain":            agent_result.get("domain", domain_result.domain),
                    "secondary_domain":  agent_result.get("secondary_domain"),
                    "domain_score":      agent_result.get("domain_score"),
                    "classifier":        "unified_agent",
                    # Carry pre-selected tools from agent so _build_tool_calls
                    # can hydrate args while governance still validates names.
                    "_agent_tools":      agent_result.get("tools", []),
                    "knowledge_source_strategy": agent_result.get("knowledge_source_strategy"),
                    "temporal_note":     agent_result.get("temporal_note", ""),
                    # RAG retrieval optimisation: hard metadata filters + query expansion
                    "_metadata_filters":  agent_result.get("metadata_filters", {}),
                    "_expanded_query":    agent_result.get("expanded_query", ""),
                }
            else:
                # Legacy path — HybridIntentClassifier
                intent = self.hybrid_clf.classify(resolved_message)

            # ── Override layer (deterministic safety) ─────────────────────
            # These are kept: they catch edge cases the LLM may miss.
            intent = self._apply_award_override(resolved_message, intent)
            intent = self._apply_download_override(resolved_message, intent)
            intent = self._apply_filmography_override(resolved_message, intent)
            intent = self._apply_news_override(resolved_message, intent)
            intent = self._normalize_award_intents(intent)
            trace["intent"] = intent
            trace["intent_raw"] = self.llm.last_intent_raw

            # ── Load EntityMemory from session context ──
            raw_stack = getattr(session_ctx, "entity_stack", None) if session_ctx else None
            raw_cats = getattr(session_ctx, "covered_categories", None) if session_ctx else None
            entity_mem = EntityMemory.from_json(raw_stack)
            # Bootstrap from legacy flat slots if stack is empty
            if not entity_mem.entities and session_ctx:
                entity_mem = EntityMemory.from_legacy_context(
                    getattr(session_ctx, "last_movie", None),
                    getattr(session_ctx, "last_person", None),
                )
            covered_categories: list[str] = deserialize_categories(raw_cats)
            # Snapshot entity state BEFORE decay for reporting
            trace["entity_stack_pre_decay"] = [
                {"value": e["value"], "type": e["type"], "score": e["score"], "recency": round(e["recency"], 3)}
                for e in entity_mem.entities
            ]
            # Decay entity scores at start of each new turn
            entity_mem.decay()

            resolved_entity = self.entity_resolver.resolve(
                resolved_message, intent, session_ctx=session_ctx
            )
            trace["entity_resolution"] = resolved_entity
            blocked, block_reason = should_block(
                intent, resolved_message, has_context=bool(session_ctx)
            )
            if blocked:
                response = {
                    "response_mode": "CLARIFICATION",
                    "text_response": block_reason,
                    "poster_url": "",
                    "streaming": [],
                    "recommendations": [],
                    "download_link": "",
                    "sources": [],
                }
                store_message(db, session_id, "user", message, token_count=len(message))
                store_message(
                    db, session_id, "assistant", json.dumps(response), token_count=len(block_reason)
                )
                trace["response_mode"] = response["response_mode"]
                trace["final_text"] = block_reason
                trace["total_llm_calls"] = (getattr(self.llm, "total_calls", 0) + getattr(self.response_client, "total_calls", 0)) - start_llm_calls
                self._write_llm_report(trace, response)
                return response, trace

            # ── Handle bot interactions as a fast path (no tools needed) ──
            if intent.get("primary_intent") == "BOT_INTERACTION":
                sys_p, usr_p, ctx_msgs, token_breakdown = build_prompt(
                    system_instructions=SYSTEM_INSTRUCTIONS,
                    user_profile={"Region": profile.region} if profile and profile.region else None,
                    recent_messages=[],
                    tool_summaries=[],
                    user_query=resolved_message,
                )
                greeting_text = self.response_client.generate_response(
                    system=sys_p, user=usr_p, context=ctx_msgs, intent="BOT_INTERACTION",
                    domain="general"
                )
                if not greeting_text:
                    greeting_text = ("Hello! 🍿 I'm FilmDB, your cinematic intelligence assistant. "
                                     "I can help you with movie details, streaming availability, "
                                     "recommendations, trending films, and much more. What would you like to explore?")
                response = {
                    "response_mode": "EXPLANATION_ONLY",
                    "text_response": greeting_text,
                    "poster_url": "",
                    "streaming": [],
                    "recommendations": [],
                    "download_link": "",
                    "sources": [],
                }
                store_message(db, session_id, "user", message, token_count=len(message))
                store_message(db, session_id, "assistant", json.dumps(response), token_count=len(greeting_text))
                trace["response_mode"] = response["response_mode"]
                trace["final_text"] = greeting_text
                trace["total_llm_calls"] = (getattr(self.llm, "total_calls", 0) + getattr(self.response_client, "total_calls", 0)) - start_llm_calls
                self._write_llm_report(trace, response)
                return response, trace

            trace["planner_raw"] = None
            trace["planner"] = None

            # ── Tier 3: Tool argument hydration + governance ──────────────────
            # If unified agent provided tools, use those names directly.
            # _build_tool_calls then fills in the correct arguments (title, person, RAG params, etc.)
            # Governance still validates, deduplicates, and caps the final list.
            if self._USE_UNIFIED_AGENT and intent.get("_agent_tools"):
                # Extract tool names from agent output
                agent_tool_names = [t["name"] for t in intent["_agent_tools"] if isinstance(t, dict) and t.get("name")]
                
                # We no longer use tool_selector.py, so we map known aliases locally or pass them through
                _aliases = {
                    "search_person": "tmdb_person_search",
                    "search_movie": "tmdb_search",
                    "get_movie_details": "retrieve_movie_data",
                }
                normalized_tools = [_aliases.get(n, n) for n in agent_tool_names]

                # For RAG calls: merge domain hints from agent's rag arguments
                _agent_rag_domains: list[str] | None = None
                for at in intent["_agent_tools"]:
                    if at.get("name") == "rag" and at.get("arguments", {}).get("domains"):
                        _agent_rag_domains = at["arguments"]["domains"]
                        break
                if _agent_rag_domains:
                    intent["_agent_rag_domains"] = _agent_rag_domains

                trace["tool_selector"] = {
                    "source":     "unified_agent",
                    "required":   normalized_tools,
                    "optional":   [],
                    "query_type": str(intent.get("primary_intent", "unknown")),
                    "entity_type": resolved_entity.get("entity_type", "unknown") if resolved_entity else "unknown",
                    "tool_group": "unified_agent",
                }
            else:
                # Legacy deterministic tool selection has been fully removed.
                raise NotImplementedError("Legacy tool selection is deprecated. Must use _USE_UNIFIED_AGENT=True.")
            tool_calls = self._build_tool_calls(
                normalized_tools,
                resolved_message,
                intent,
                resolved_entity,
                profile,
            )
            tool_calls = self._apply_download_policy(tool_calls, intent, resolved_entity)
            # E.4 — Governance: raise cap for academic queries that require extensive RAG
            academic_intents = {"FILM_ANALYSIS", "CONCEPTUAL_EXPLANATION", "MOVEMENT_OVERVIEW",
                                "VISUAL_ANALYSIS", "THEORETICAL_ANALYSIS", "DIRECTOR_ANALYSIS",
                                "HISTORICAL_CONTEXT", "STYLE_COMPARISON", "FILM_COMPARISON"}
            award_intents = {"AWARD_LOOKUP", "OSCAR_LOOKUP", "GENERAL_AWARD_LOOKUP"}
            if intent.get("primary_intent") in academic_intents:
                tool_cap = 6
            elif intent.get("primary_intent") in award_intents:
                tool_cap = 3  # oscar_award + imdb_awards + wikipedia — tight, focused
            else:
                tool_cap = 4

            approved_calls, rejected_calls = filter_tool_calls(
                resolved_message, tool_calls, max_tools=tool_cap, return_rejections=True
            )
            
            # E.6 — Fallback to Web Search if zero tools survived and it's not illegal/bot interaction
            if not approved_calls and intent.get("primary_intent") not in ("BOT_INTERACTION", "ILLEGAL_DOWNLOAD_REQUEST"):
                self.logger.warning("Zero tools approved for query '%s'. Forcing cinema_search fallback.", resolved_message)
                approved_calls = [{"name": "cinema_search", "arguments": {"query": resolved_message}}]
                
            self.logger.info("Approved tool calls: %s", approved_calls)
            self.logger.info("Rejected tool calls: %s", rejected_calls)
            trace["tool_calls_proposed"] = tool_calls
            trace["tool_calls_approved"] = approved_calls
            trace["tool_calls_rejected"] = rejected_calls

            tool_outputs, tool_trace = await self._execute_tools(
                session_id, approved_calls, profile, resolved_message
            )

            # E.7 — Dynamic Fallback: Intercept empty DB results for recent entities
            # If TMDB/RAG failed and no web search was performed, force one
            failed_db = False
            for t_name, t_out in tool_outputs.items():
                if t_name in ("tmdb", "rag") and t_out.get("status") in ("not_found", "error"):
                    failed_db = True

            if failed_db and "cinema_search" not in tool_outputs:
                self.logger.warning("Primary database tool returned empty. Triggering automatic cinema_search fallback for '%s'", resolved_message)
                fb_calls = [{"name": "cinema_search", "arguments": {"query": resolved_message}}]
                fb_out, fb_trace = await self._execute_tools(
                    session_id, fb_calls, profile, resolved_message
                )
                tool_outputs.update(fb_out)
                if "tool_timings" in tool_trace and "tool_timings" in fb_trace:
                    tool_trace["tool_timings"].extend(fb_trace["tool_timings"])
            trace["tool_outputs"] = tool_outputs
            trace["tool_execution"] = tool_trace

            # ── Dynamic Instruction Injection ──
            tool_summaries = summarize_all(tool_outputs)
            primary_intent = intent.get("primary_intent", "ENTITY_LOOKUP")
            domain = intent.get("domain", "structured_data")
            dynamic_instr = SYSTEM_INSTRUCTIONS
            
            # Temporal awareness (Prepend to top so it's never ignored)
            current_date_str = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
            temporal_header = (
                f"TEMPORAL CONTEXT: Today is {current_date_str}. "
                f"Your training knowledge cutoff is approximately March 2025. "
                f"For events, releases, awards, or news after March 2025, rely only on provided tool data — do NOT guess. "
                f"If no tool data covers recent events the user asks about, clearly state your knowledge cutoff.\n\n"
            )
            dynamic_instr = temporal_header + dynamic_instr

            # Streaming context
            if primary_intent == "STREAMING_AVAILABILITY":

                dynamic_instr += "\n\nSESSION CONTEXT: The user is asking for streaming availability. You MUST provide a dedicated 'Streaming Availability' section listing all platforms from the reference data."
            else:
                dynamic_instr += "\n\nSESSION CONTEXT: Do NOT mention streaming platforms or 'Where to Watch' in your text response — this is already shown in the UI card footer. Focus on other aspects."

            # Follow-up hint injection (Option B + C)
            current_category = classify_query_category(resolved_message, primary_intent)
            followup_hints = generate_followups(
                covered_categories=covered_categories,
                current_category=current_category,
                primary_entity=entity_mem.primary_movie() or entity_mem.primary_person(),
            )

            if followup_hints:
                hints_str = " | ".join(followup_hints)
                dynamic_instr += (
                    f"\n\nFOLLOW-UP SUGGESTIONS: At the end of your response, add 1 brief natural sentence suggesting "
                    f"what the user might explore next. Choose from: [{hints_str}]. "
                    f"Skip it entirely for very short factual answers."
                )


            # B.1 — Pass last 3 turns (6 messages) of conversation history to the LLM
            _recent_raw = fetch_last_messages(db, session_id, limit=6)
            _recent_msgs = []
            for m in reversed(_recent_raw):
                text_content = m.content
                if m.role == "assistant":
                    try:
                        parsed = json.loads(m.content)
                        if isinstance(parsed, dict) and "text_response" in parsed:
                            text_content = parsed["text_response"]
                    except Exception:
                        pass
                _recent_msgs.append({"role": m.role, "content": text_content})

            sys_p, usr_p, ctx_msgs, token_breakdown = build_prompt(
                system_instructions=dynamic_instr,
                user_profile={"Region": profile.region} if profile and profile.region else None,
                recent_messages=_recent_msgs,
                tool_summaries=tool_summaries,
                user_query=resolved_message,
            )

            final_text = self.response_client.generate_response(
                system=sys_p, user=usr_p, context=ctx_msgs, intent=primary_intent,
                domain=domain
            )
            usage = getattr(self.response_client, "last_usage", None)

            # [Grounding Retry Removed to save LLM Call count]
            # Reliability is now handled by aggressive primary prompt instructions above.

            if not final_text:
                # A.4 — Intent-aware fallback (replaces the silent generic string)
                _ERR = "the server is not reachable due to llm limit"
                _FALLBACK = {
                    "FILM_ANALYSIS":      _ERR,
                    "ANALYTICAL_EXPLANATION": _ERR,
                    "ENTITY_LOOKUP":      _ERR,
                    "PERSON_LOOKUP":      _ERR,
                    "RECOMMENDATION":     _ERR,
                    "CRITIC_REVIEW":      _ERR,
                    "AWARD_LOOKUP":       _ERR,
                    "STREAMING_AVAILABILITY": _ERR,
                }
                final_text = _FALLBACK.get(
                    intent.get("primary_intent", ""),
                    _ERR,
                )
            # Post-generation validation: strip bad headers, log quality issues
            final_text = self._validate_response(final_text, intent, tool_outputs, _recent_msgs)
            trace["final_text"] = final_text

            response_mode = select_response_mode(
                intent.get("primary_intent", "ENTITY_LOOKUP"),
                intent.get("secondary_intents", []),
                tool_outputs,
            )
            response = self._build_response(final_text, tool_outputs)
            response["response_mode"] = response_mode
            trace["response_mode"] = response_mode
            # Dynamic layout: compute segment list from the fully-built response dict
            # so the selector can inspect real data (poster_url, awards, trailer_key …)
            response["layout_segments"] = select_layout_segments(
                intent.get("primary_intent", "ENTITY_LOOKUP"),
                intent.get("secondary_intents", []),
                tool_outputs,
                response,
            )

            # Generate smart chat title for the first turn (DE-LLM'd for efficiency)
            if not _recent_msgs:
                # Deterministic Title: Use the resolved entity name if available, else truncate query.
                if resolved_entity.get("entity_value"):
                    chat_title = resolved_entity["entity_value"]
                else:
                    words = message.split()
                    chat_title = " ".join(words[:4]) + ("..." if len(words) > 4 else "")
                
                response["session_title"] = chat_title.strip(' \n".\'')

            # Store the final response dictionary to SQLite so the UI gets posters/streaming on reload
            p_tokens = usage.prompt_tokens if usage else len(message)
            c_tokens = usage.completion_tokens if usage else len(final_text)

            # Normalize breakdown if we have factual data
            final_breakdown = token_breakdown
            if usage and usage.prompt_tokens > 0:
                estimated_total = sum(v for v in token_breakdown.values() if isinstance(v, (int, float)))
                estimated_total += sum(token_breakdown.get("tools", {}).values())
                if estimated_total > 0:
                    scale = usage.prompt_tokens / estimated_total
                    final_breakdown = {
                        "system_core": int(token_breakdown["system_core"] * scale),
                        "history": int(token_breakdown["history"] * scale),
                        "user_query": int(token_breakdown["user_query"] * scale),
                        "tools": {k: int(v * scale) for k, v in token_breakdown["tools"].items()}
                    }
            
            store_message(db, session_id, "user", message, token_count=p_tokens)
            store_message(db, session_id, "assistant", json.dumps(response), token_count=c_tokens)
            
            trace["prompt_tokens"] = p_tokens
            trace["completion_tokens"] = c_tokens
            trace["token_breakdown"] = final_breakdown

            # A.5 — Guard: don't write award ceremony names into last_person
            _PERSON_BLACKLIST = {
                "oscar", "oscars", "academy", "academy awards", "bafta",
                "golden globe", "golden globes", "emmy", "grammy", "screen actors guild",
            }
            def _safe_person(val: str | None) -> str | None:
                if not val:
                    return None
                if val.lower().strip().split()[0] in _PERSON_BLACKLIST:
                    return None
                return val

            # A.5 — Context Hysteresis Fix: Keep movie/person sticky
            new_movie = self._extract_movie_from_tools(tool_outputs)
            new_person = _safe_person(
                self._extract_person_from_intent(intent)
                or (
                    resolved_entity.get("entity_value")
                    if resolved_entity.get("entity_type") == "person"
                    else None
                )
            )

            final_movie = new_movie or (session_ctx.last_movie if session_ctx else None)
            final_person = new_person or (session_ctx.last_person if session_ctx else None)

            # ── Update EntityMemory with this turn's entities ──
            if final_movie:
                entity_mem.add(final_movie, "movie", "primary")
            if final_person:
                role = "secondary" if final_movie else "primary"
                entity_mem.add(final_person, "person", role)
            # Mark this category as covered
            covered_categories.append(current_category)

            upsert_session_context(
                db,
                session_id=session_id,
                last_movie=final_movie,
                last_person=final_person,
                last_entity=resolved_entity.get("entity_value"),
                entity_type=resolved_entity.get("entity_type"),
                last_intent=intent.get("primary_intent"),
                entity_stack=entity_mem.entities,
                covered_categories=covered_categories,
            )
            session_ctx_after = get_session_context(db, session_id)
            trace["session_context_after"] = (
                {
                    "last_movie": session_ctx_after.last_movie,
                    "last_person": session_ctx_after.last_person,
                    "last_entity": getattr(session_ctx_after, "last_entity", None),
                    "entity_type": getattr(session_ctx_after, "entity_type", None),
                    "last_intent": session_ctx_after.last_intent,
                    "entity_stack": str(entity_mem),
                    "covered_categories": covered_categories,
                }
                if session_ctx_after
                else None
            )
            # Capture entity lifecycle snapshot for the report
            trace["entity_lifecycle"] = {
                "stack_before_decay": trace.get("entity_stack_pre_decay", []),
                "stack_after": [
                    {
                        "value":     e["value"],
                        "type":      e["type"],
                        "role":      e["role"],
                        "score":     e["score"],
                        "recency":   round(e["recency"], 3),
                        "frequency": e["frequency"],
                    }
                    for e in entity_mem.entities
                ],
                "added_this_turn": [
                    v for v in [final_movie, final_person] if v
                ],
                "primary_entity": str(entity_mem.primary() or {}).replace("{", "").replace("}", ""),
                "covered_categories": covered_categories,
                "current_category":   current_category,
                "followup_hints":     followup_hints if followup_hints else [],
            }
            trace["total_llm_calls"] = (getattr(self.llm, "total_calls", 0) + getattr(self.response_client, "total_calls", 0)) - start_llm_calls
            self._write_llm_report(trace, response)
            # Capture Qwen3 reasoning trace from client for metadata
            trace["reasoning_trace"] = getattr(self.response_client, "last_think_trace", "")
            self.logger.info("FINISHED process_message. Total LLM calls for this query: %s", trace["total_llm_calls"])
            return response, trace
        except Exception as e:
            self.logger.exception("Fatal error in _run_internal")
            import traceback
            trace["fatal_error"] = f"{type(e).__name__}: {str(e)}"
            trace["fatal_error_tb"] = traceback.format_exc()
            trace["total_llm_calls"] = (getattr(self.llm, "total_calls", 0) + getattr(self.response_client, "total_calls", 0)) - start_llm_calls
            self._write_llm_report(trace, {"response_mode": "FATAL_ERROR", "text_response": "Internal Server Error."})
            raise
        finally:
            db.close()

    # ════════════════════════════════════════════════════════════════
    #  RESPONSE VALIDATION (P2 fix #10)
    # ════════════════════════════════════════════════════════════════

    def _validate_response(self, text: str, intent: dict, tool_outputs: list,
                           recent_msgs: list[dict]) -> str:
        """Post-generation quality checks. Returns cleaned text or triggers fixes."""
        if not text:
            return text

        # Fix 1: Strip generic opening headers the model keeps generating
        import re
        text = re.sub(
            r'^##\s*(Introduction to|Overview of|Background on)\s+',
            '## ',
            text,
            flags=re.MULTILINE,
        )

        # Fix 2: Remove trailing "Conclusion" sections
        text = re.sub(
            r'\n##\s*Conclusion\s*\n.*$',
            '',
            text,
            flags=re.DOTALL,
        )

        # Fix 3: Log warning if model ignores tool data
        has_successful_tools = any(
            isinstance(t, dict) and t.get("status") == "success"
            for t in tool_outputs
        ) if tool_outputs else False

        if has_successful_tools and any(
            phrase in text.lower()
            for phrase in ["i don't have access", "i don't have information",
                          "i couldn't find", "no data available",
                          "based on my knowledge cutoff"]
        ):
            self.logger.warning(
                "Response claims lack of data despite successful tool outputs. "
                "Intent: %s", intent.get('primary_intent')
            )

        # Fix 4: Log if response is suspiciously short for a non-interaction
        primary = intent.get("primary_intent", "")
        if len(text) < 80 and primary not in ("BOT_INTERACTION", "DOWNLOAD"):
            self.logger.warning(
                "Very short response (%d chars) for intent %s", len(text), primary
            )

        return text.strip()

    def _propose_tools(self, message: str) -> Dict[str, Any]:
        return {"tools_required": [], "confidence": 100, "reasoning": ""}

    def _build_tool_calls(
        self,
        tool_names: list[str],
        message: str,
        intent: dict[str, Any],
        resolved_entity: dict[str, Any],
        profile,
    ) -> list[dict[str, Any]]:
        primary = intent.get("primary_intent", "")
        
        extracted_movie = None
        extracted_person = None
        if resolved_entity.get("entity_type") == "movie":
            extracted_movie = resolved_entity.get("entity_value")
        elif resolved_entity.get("entity_type") == "person":
            extracted_person = resolved_entity.get("entity_value")
            
        extracted_person = extracted_person or self._extract_person_from_intent(intent)

        title = extracted_movie or message
        person_name = extracted_person or ""

        region = None
        if profile and getattr(profile, "region", None):
            region = profile.region

        # Extract second entity for comparison
        title_b = ""
        person_name_b = ""
        if primary == "COMPARISON":
            entities = intent.get("entities", [])
            movie_entities = [e for e in entities if isinstance(e, dict) and e.get("type") == "movie"]
            if len(movie_entities) >= 2:
                title = movie_entities[0].get("value", title)
                title_b = movie_entities[1].get("value", "")
            
            person_entities = [e for e in entities if isinstance(e, dict) and e.get("type") == "person"]
            if len(person_entities) >= 2:
                person_name = person_entities[0].get("value", person_name)
                person_name_b = person_entities[1].get("value", "")

        # Extract genre/year/language for top_rated
        genre_filter = None
        year_filter = None
        language_filter = None
        entities = intent.get("entities", [])
        for ent in entities:
            if isinstance(ent, dict):
                if ent.get("type") == "genre":
                    genre_filter = ent.get("value")
                elif ent.get("type") == "year":
                    year_filter = ent.get("value")

        # Try to extract genre/language from the message itself
        lowered = message.lower()
        for lang in ["tamil", "hindi", "malayalam", "telugu", "kannada", "bengali", "marathi"]:
            if lang in lowered:
                language_filter = lang.capitalize()
                break
        for g in ["action", "comedy", "drama", "horror", "thriller",
                  "romance", "sci-fi", "animation", "documentary", "mystery"]:
            if g in lowered and not genre_filter:
                genre_filter = g.capitalize()
                break

        tool_calls = []
        for name in tool_names:
            args: dict[str, Any] = {}
            # ── API tools ────────────────────────────────────────────────
            if name in ("wikipedia", "archive"):
                args = {"title": title}
            elif name == "imdb_awards":
                if extracted_person and not extracted_movie:
                    args = {"person_name": extracted_person}
                else:
                    args = {"title": title}
            elif name == "tmdb":
                args = {"title": title}
                if resolved_entity.get("year"):
                    args["year"] = resolved_entity.get("year")
                if primary in ("PERSON_LOOKUP", "FILMOGRAPHY") or extracted_person or person_name_b:
                    args = {"name": person_name or message}
            elif name == "watchmode":
                args = {"title": title, "region": region or "IN"}
            elif name == "cinema_search":
                priority_groups = self._get_cinema_priority_groups(message, intent, resolved_entity)
                args = {"query": message, "priority_groups": priority_groups}
            elif name == "recommendation_engine":
                args = {"query": message, "profile": "SIMILARITY"}
            elif name == "oscar_award":
                if extracted_person and not extracted_movie:
                    args = {"person_name": extracted_person}
                else:
                    args = {"movie_title": title}
            # ── RAG unified tool ──────────────────────────────────────────
            elif name == "rag":
                # Derive query_type directly from the unified agent's explicit semantic intent string
                _qt = str(intent.get("primary_intent", "ENTITY_LOOKUP"))
                # If the unified agent specified target RAG domains, honour them
                _agent_rag_domains = intent.get("_agent_rag_domains")
                # Use expanded_query from router if available, fallback to raw message
                _expanded_q = intent.get("_expanded_query", "") or ""
                args = {
                    "query":            _expanded_q if _expanded_q.strip() else message,
                    "query_type":       _qt,
                    "primary_domain":   (_agent_rag_domains[0] if _agent_rag_domains else intent.get("domain")),
                    "secondary_domain": (_agent_rag_domains[1] if _agent_rag_domains and len(_agent_rag_domains) > 1 else intent.get("secondary_domain")),
                    "imdb_id":          resolved_entity.get("canonical_id") if resolved_entity.get("entity_type") == "movie" else None,
                    "person_name":      extracted_person or None,
                    "metadata_filters": intent.get("_metadata_filters", {}),
                }

            tool_calls.append({"name": name, "arguments": args})

            # ── Add secondary call for Comparison if entity B exists ──
            if primary == "COMPARISON":
                if title_b and name in ("wikipedia", "kb_plot", "tmdb"):
                    args_b = dict(args)
                    args_b["title"] = title_b
                    if name == "tmdb": args_b.pop("name", None)
                    tool_calls.append({"name": f"{name}_b", "arguments": args_b})
                elif person_name_b and name in ("wikipedia", "kb_filmography", "tmdb"):
                    args_b = dict(args)
                    if "name" in args_b: args_b["name"] = person_name_b
                    if name == "wikipedia": args_b["title"] = person_name_b
                    if name == "tmdb":
                         args_b["name"] = person_name_b
                         args_b.pop("title", None)
                    tool_calls.append({"name": f"{name}_b", "arguments": args_b})

        return tool_calls

    def _get_cinema_priority_groups(self, message: str, intent: dict, resolved_entity: dict) -> List[str]:
        """Determine which site groups to prioritize based on query context."""
        priority = []
        lowered = message.lower()
        primary_intent = intent.get("primary_intent", "")
        domain = intent.get("domain", "")
        entities = intent.get("entities", [])

        # Step 0: Extract LLM-detected Supporting Entities (Phase 19 Smart Fallback)
        llm_region = next((e["value"].lower() for e in entities if e.get("type") == "region"), None)
        llm_category = next((e["value"].lower() for e in entities if e.get("type") == "category"), None)

        # 1. Awards Intent / Category
        if primary_intent == "AWARD_LOOKUP" or llm_category == "awards" or any(k in lowered for k in ["oscar", "cannes", "award", "winner"]):
            priority.append("awards")

        # 2 & 3. Regional Cinema Detection
        is_tamil = "tamil" in lowered or "kollywood" in lowered or llm_region == "tamil"
        is_indian = any(k in lowered for k in ["bollywood", "hindi", "indian cinema"]) or llm_region == "indian"
        
        if (not is_tamil or not is_indian) and resolved_entity.get("canonical_id"):
            try:
                from kb.engine.filmdb_query_engine import FilmDBQueryEngine
                engine = FilmDBQueryEngine.get_instance()
                movie_data = engine.entity_lookup(resolved_entity["canonical_id"])
                
                if movie_data:
                    lang = movie_data.get("original_language")
                    if lang == "ta":
                        is_tamil = True
                    elif lang in ("hi", "ml", "te", "kn"):
                        is_indian = True
            except Exception:
                pass
        
        if is_tamil:
            priority.append("tamil")
        if is_indian and not is_tamil:
            priority.append("indian")

        # 4. Academic/Criticism
        if domain in ("film_theory", "film_criticism"):
            # Academic queries benefit from both Indian criticism and Global trades
            if "indian" not in priority: priority.append("indian")
            if "global" not in priority: priority.append("global")

        # 5. Global Default
        if not priority:
            priority.append("global")
            
        return priority

    def _resolve_pronouns(self, message: str, session_ctx) -> str:
        if not session_ctx:
            return message
        text = message.lower()

        def _has_word(word: str) -> bool:
            return bool(re.search(r'\b' + re.escape(word) + r'\b', text))

        def _has_phrase(phrase: str) -> bool:
            return phrase in text

        if any(_has_word(p) for p in ["him", "her", "his", "hers"]) and session_ctx.last_person:
            return message + f" (refers to {session_ctx.last_person})"
        # Movie references — check multi-word phrases first, then single words
        movie_phrases = ["the film", "the movie", "that movie", "that film",
                         "this film", "this movie"]
        movie_words = ["it", "its"]
        if (any(_has_phrase(p) for p in movie_phrases) or
                any(_has_word(p) for p in movie_words)) and session_ctx.last_movie:
            return message + f" (refers to {session_ctx.last_movie})"
        if any(_has_word(p) for p in ["it", "its", "that", "this"]) and session_ctx.last_entity:
            return message + f" (refers to {session_ctx.last_entity})"
        return message

    def _apply_award_override(self, message: str, intent: dict[str, Any]) -> dict[str, Any]:
        lowered = message.lower()
        if any(k in lowered for k in ["oscar", "oscars", "academy awards", "best picture"]):
            intent = dict(intent)
            intent["primary_intent"] = "OSCAR_LOOKUP"
            intent["confidence"] = 100
        elif any(k in lowered for k in ["award", "awards", "golden globe", "emmy", "grammy"]):
            if intent.get("primary_intent") not in ("OSCAR_LOOKUP", "GENERAL_AWARD_LOOKUP"):
                intent = dict(intent)
                intent["primary_intent"] = "GENERAL_AWARD_LOOKUP"
                intent["confidence"] = 100
        return intent

    def _apply_filmography_override(self, message: str, intent: dict[str, Any]) -> dict[str, Any]:
        """Override ENTITY_LOOKUP → FILMOGRAPHY for 'best movies by X' style queries."""
        lowered = message.lower()
        if intent.get("primary_intent") not in ("ENTITY_LOOKUP", "TOP_RATED"):
            return intent
        if re.search(r"\b(?:best|top|great(?:est)?|famous|notable|popular)\s+(?:movies?|films?)\s+(?:by|of|from)\b", lowered):
            intent = dict(intent)
            intent["primary_intent"] = "FILMOGRAPHY"
            intent["confidence"] = 95
            self.logger.info("FILMOGRAPHY override: '%s'", message)
        return intent

    def _apply_news_override(self, message: str, intent: dict[str, Any]) -> dict[str, Any]:
        """Strict override for news keywords to ensure web search tools are prioritized."""
        lowered = message.lower()
        news_keywords = ["latest news", "breaking news", "updates about", "current status", "recent developments", "what is the latest"]
        if any(k in lowered for k in news_keywords):
            intent = dict(intent)
            intent["primary_intent"] = "LATEST_NEWS"
            intent["confidence"] = 100
            intent["domain"] = "structured_data"
            self.logger.info("NEWS override (structured_data): '%s'", message)
        return intent

    def _apply_download_override(self, message: str, intent: dict[str, Any]) -> dict[str, Any]:
        lowered = message.lower()
        if "download" not in lowered and "watch for free" not in lowered:
            return intent
        intent = dict(intent)
        piracy_keywords = ["torrent", "pirated", "cracked", "free download", "yts", "1337x", "rarbg"]
        if any(k in lowered for k in piracy_keywords):
            intent["primary_intent"] = "ILLEGAL_DOWNLOAD_REQUEST"
            intent["confidence"] = 100
        else:
            intent["primary_intent"] = "LEGAL_DOWNLOAD"
        return intent

    def _normalize_award_intents(self, intent: dict[str, Any]) -> dict[str, Any]:
        """Canonicalize award intents to AWARD_LOOKUP for consistent routing."""
        primary = intent.get("primary_intent")
        if primary not in ("OSCAR_LOOKUP", "GENERAL_AWARD_LOOKUP"):
            return intent
        normalized = dict(intent)
        normalized["primary_intent"] = "AWARD_LOOKUP"
        return normalized

    def _apply_download_policy(
        self, tool_calls: list[dict[str, Any]], intent: dict[str, Any], resolved_entity: dict[str, Any]
    ) -> list[dict[str, Any]]:
        # Archive component handles its own fallback. Since the tool_selector automatically
        # pushes download intents to the archive tool, we don't need to filter or append here anymore.
        return tool_calls

    def _needs_grounding_retry(self, tool_outputs: dict[str, dict], final_text: str, intent: dict[str, Any]) -> bool:
        # B.5 — Expanded: retry grounding for ANY intent that had at least one
        # successful tool call, not just 3 specific intents.
        primary_intent = intent.get("primary_intent", "")
        if primary_intent in ("BOT_INTERACTION",):
            return False
        if not tool_outputs:
            return False

        # If any tool succeeded, check that key facts appear in the response
        any_tool_ok = any(
            isinstance(v, dict) and v.get("status") in ("success", "ok")
            for v in tool_outputs.values()
        )
        if not any_tool_ok:
            return False

        # Check API IMDb data
        imdb = tool_outputs.get("imdb")
        if imdb and imdb.get("status") == "success":
            rating = imdb.get("data", {}).get("rating")
            year = imdb.get("data", {}).get("year")
            if rating and str(rating) not in final_text:
                return True
            if year and str(year) not in final_text:
                return True
        # Check Live TMDB data
        tmdb_out = tool_outputs.get("tmdb")
        if tmdb_out and tmdb_out.get("status") == "success":
            rating = tmdb_out.get("data", {}).get("rating")
            year = tmdb_out.get("data", {}).get("year")
            if rating and str(rating) not in final_text:
                return True
            if year and str(year) not in final_text:
                return True
        return False

    def _extract_movie_from_tools(self, tool_outputs: dict[str, dict]) -> str | None:
        imdb = tool_outputs.get("imdb")
        if imdb and imdb.get("status") == "success":
            return imdb.get("data", {}).get("title")
        tmdb_out = tool_outputs.get("tmdb")
        if tmdb_out and tmdb_out.get("status") == "success":
            return tmdb_out.get("data", {}).get("title")
        return None

    def _extract_person_from_intent(self, intent: dict[str, Any]) -> str | None:
        entities = intent.get("entities", [])
        for ent in entities:
            if isinstance(ent, dict):
                entity_type = str(ent.get("type", "")).lower()
                if entity_type in ("person", "director", "actor", "filmmaker", "creator"):
                    val = ent.get("value")
                    if val:
                        return str(val)
        return None

    async def _execute_tools(
        self, session_id: str, tool_calls: List[Dict[str, Any]], profile, message: str
    ) -> tuple[Dict[str, Dict], dict[str, Any]]:
        tasks = []
        tool_names = []
        cached_outputs: Dict[str, Dict] = {}
        cache_hits: list[str] = []
        cache_misses: list[str] = []
        db = SessionLocal()
        try:
            title = None
            for call in tool_calls:
                args = call.get("arguments", {})
                if "title" in args:
                    title = args.get("title")
                    break

            if title:
                metadata_cache = get_metadata_cache(db, title)
                if metadata_cache:
                    if metadata_cache.imdb_data is not None:
                        cached_outputs["imdb"] = {
                            "status": "success",
                            "data": metadata_cache.imdb_data,
                        }
                        cache_hits.append("imdb")
                    else:
                        cache_misses.append("imdb")
                    if metadata_cache.wikipedia_data is not None:
                        cached_outputs["wikipedia"] = {
                            "status": "success",
                            "data": metadata_cache.wikipedia_data,
                        }
                        cache_hits.append("wikipedia")
                    else:
                        cache_misses.append("wikipedia")

                region = getattr(profile, "region", None) if profile else None
                approved_tool_names = {c.get("name") for c in tool_calls if isinstance(c, dict)}
                if region and "watchmode" in approved_tool_names:
                    streaming_cache = get_streaming_cache(db, title, region)
                    if streaming_cache:
                        cached_outputs["watchmode"] = {
                            "status": "success",
                            "data": streaming_cache.streaming_data,
                        }
                        cache_hits.append("watchmode")
                    else:
                        cache_misses.append("watchmode")


        finally:
            db.close()

        outputs: Dict[str, Dict] = dict(cached_outputs)

        imdb_id = None  # resolved lazily below when award tools are present
        # ── Pre-process: Resolve IMDb ID for both award tools ──
        award_calls = [c for c in tool_calls if c.get("name") in ("imdb_awards", "oscar_award")]
        if award_calls:
            # Try to resolve title → IMDb ID once and share it
            if not imdb_id:
                from kb.engine.filmdb_query_engine import FilmDBQueryEngine
                engine = FilmDBQueryEngine.get_instance()
                imdb_id = engine.resolve_title_to_imdb_id(title)

            for call in award_calls:
                call_args = call.setdefault("arguments", {})
                resolved_id = imdb_id

                if "person_name" in call_args and call_args["person_name"]:
                    engine = FilmDBQueryEngine.get_instance()
                    res = engine.person_filmography(call_args["person_name"])
                    if res and "nconst" in res:
                        resolved_id = res["nconst"]
                elif not resolved_id:
                    engine = FilmDBQueryEngine.get_instance()
                    resolved_id = engine.resolve_title_to_imdb_id(
                        call_args.get("title") or call_args.get("movie_title") or ""
                    )

                if resolved_id:
                    call_args["imdb_id"] = resolved_id
                else:
                    call_name = call.get("name")
                    title_or_person = (
                        call_args.get("title")
                        or call_args.get("movie_title")
                        or call_args.get("person_name")
                        or ""
                    )
                    outputs[call_name] = {
                        "status": "not_found",
                        "data": {"query": title_or_person, "reason": "imdb_id_not_found"},
                    }

        for call in tool_calls:
            tool_name = call.get("name")
            args = call.get("arguments", {})
            # Only dispatch if tool_name is a string and not None
            if not isinstance(tool_name, str) or tool_name in outputs:
                continue
            task = self._dispatch_tool(tool_name, args, profile)
            if task:
                tool_names.append((tool_name, args))
                tasks.append(task)

        async def _time_task(task_coro):
            start = time.monotonic()
            try:
                res = await task_coro
                return res, int((time.monotonic() - start) * 1000)
            except Exception as e:
                return e, int((time.monotonic() - start) * 1000)

        timed_tasks = [_time_task(t) for t in tasks]
        try:
            results_with_times = await asyncio.wait_for(
                asyncio.gather(*timed_tasks),
                timeout=45.0,
            )
        except asyncio.TimeoutError:
            self.logger.warning("Tool execution timed out after 45s")
            results_with_times = [(TimeoutError("Tool execution timed out"), 45000) for _ in tasks]
            
        timings: list[dict[str, Any]] = []

        for idx, ((tool_name, args), (result, elapsed_ms)) in enumerate(zip(tool_names, results_with_times)):
            status = "error"
            output = {"status": "error", "data": {}}
            error_detail = None
            if isinstance(result, Exception):
                error_detail = f"{type(result).__name__}: {str(result)}"
                self.logger.exception(f"Tool {tool_name} failed with exception", exc_info=result)
            elif isinstance(result, dict):
                output = result
                status = result.get("status", "error")
                if status == "error":
                    error_detail = result.get("data", {}).get("error") or result.get("error", "Unknown tool error")

            outputs[tool_name] = output
            store_tool_call(session_id, tool_name, args, status, elapsed_ms)
            timings.append(
                {
                    "tool": tool_name,
                    "status": status,
                    "execution_time_ms": elapsed_ms,
                    "arguments": args,
                    "error_detail": error_detail,
                }
            )

        self._update_caches(outputs)
        trace = {
            "cache_hits": sorted(set(cache_hits)),
            "cache_misses": sorted(set(cache_misses)),
            "tool_timings": timings,
        }
        return outputs, trace

    def _dispatch_tool(self, tool_name: str, args: Dict[str, Any], profile):
        region = None
        if profile and getattr(profile, "region", None):
            region = profile.region
        
        # Handle suffix for comparison B calls
        base_name = tool_name
        if tool_name.endswith("_b"):
            base_name = tool_name[:-2]

        if base_name == "wikipedia":
            return services.wikipedia_service.run(args.get("title", ""))
        if base_name == "tmdb":
            if "name" in args:
                return services.tmdb_service.get_person(args.get("name", ""))
            return services.tmdb_service.run(args.get("title", ""))
        if base_name == "watchmode":
            return services.watchmode_service.run(args.get("title", ""), args.get("region") or region)
        if base_name == "imdb_awards":
            return services.imdb_awards_service.run(imdb_id=args.get("imdb_id", ""))
        if base_name == "archive":
            return services.archive_service.run(args.get("title", ""))
        if base_name == "cinema_search":
            return services.cinema_search_service.run(args.get("query", ""))
        # ── KB tools ─────────────────────────────────────────────────────
        if base_name == "oscar_award":
            return oscar_award.run(movie_title=args.get("movie_title"), person_name=args.get("person_name"))
        if base_name == "recommendation_engine":
            return recommendation_engine.run(
                query=args.get("query", ""),
                imdb_id=args.get("imdb_id", ""),
                profile=args.get("profile", "SIMILARITY")
            )
        # Deprecated KB tools (moved to RAG) removed
        # ── Unified RAG tool ──────────────────────────────────────────────────
        if base_name == "rag":
            async def _rag_unified_call(
                q=args.get("query", ""),
                qt=args.get("query_type", "factual"),
                pd=args.get("primary_domain"),
                sd=args.get("secondary_domain"),
                iid=args.get("imdb_id"),
                pname=args.get("person_name"),
                mf=args.get("metadata_filters"),
            ):
                try:
                    from app.services.rag.rag_service import RAGService
                    rag = RAGService.get_instance()
                    results = rag.query_unified(
                        query=q,
                        query_type=qt,
                        primary_domain=pd,
                        secondary_domain=sd,
                        imdb_id=iid,
                        person_name=pname,
                        metadata_filters=mf,
                    )
                    if not results:
                        return {"status": "not_found", "data": {"passages": []}}
                    return {
                        "status": "success",
                        "data": {
                            "passages": results,
                            "source": "rag_unified",
                            "query_type": qt,
                        },
                    }
                except FileNotFoundError:
                    return {"status": "not_found", "data": {"reason": "index_not_built_yet"}}
                except Exception as exc:
                    self.logger.warning("rag failed: %s", exc)
                    return {"status": "error", "data": {"error": str(exc)}}
            return _rag_unified_call()

        return None

    def _build_response(self, text: str, tool_outputs: Dict[str, Dict]) -> Dict[str, Any]:
        response = {
            "text_response": text,
            "poster_url": "",
            "streaming": [],
            "recommendations": [],
            "download_link": "",
            "sources": [],
            "title": "",
            "year": "",
            "director": "",
            "rating": "",
            # ── New enriched fields ──
            "entity_type": "",       # "movie" | "person"
            "person_name": "",
            "profession": "",
            "birth_date": "",
            "genres": [],
            "trailer_key": "",
            "awards": {},
        }
        # Data from IMDb/TMDB API
        imdb = tool_outputs.get("imdb")
        if imdb and imdb.get("status") == "success":
            data = imdb.get("data", {})
            response["poster_url"] = data.get("poster_url", "")
            response["title"] = data.get("title", "")
            response["year"] = data.get("year", "")
            response["director"] = data.get("director", "")
            response["rating"] = data.get("rating", "")
        # Data from TMDB Service
        tmdb_out = tool_outputs.get("tmdb")
        if tmdb_out and tmdb_out.get("status") == "success":
            data = tmdb_out.get("data", {})
            if "name" in data:  # Person data
                response["entity_type"] = "person"
                response["person_name"] = data.get("name", "")
                response["profession"] = data.get("profession", "")
                response["birth_date"] = data.get("birth_date", "")
                if not response["poster_url"]:
                    response["poster_url"] = data.get("poster_url", "")
            else:  # Movie data
                response["entity_type"] = "movie"
                if not response["poster_url"]:
                    response["poster_url"] = data.get("poster_url", "")
                if not response["title"]:
                    response["title"] = data.get("title", "")
                if not response["year"]:
                    response["year"] = data.get("year", "")
                if not response["rating"]:
                    response["rating"] = data.get("rating", "")
                if not response["director"]:
                    response["director"] = data.get("director", "")
                if not response["genres"]:
                    response["genres"] = data.get("genres", [])
                if not response["trailer_key"]:
                    response["trailer_key"] = data.get("trailer_key", "")
                # Phase 20 additions
                response["runtime_minutes"] = data.get("runtime_minutes")
                response["tagline"] = data.get("tagline")
        imdb_person = tool_outputs.get("imdb_person")
        if imdb_person and imdb_person.get("status") == "success":
            response["poster_url"] = (
                imdb_person.get("data", {}).get("poster_url") or response["poster_url"]
            )
        watchmode = tool_outputs.get("watchmode")
        if watchmode and watchmode.get("status") == "success":
            response["streaming"] = watchmode.get("data", {}).get("platforms", []) or watchmode.get(
                "data", {}
            ).get("providers", [])
        similarity = tool_outputs.get("similarity")
        if similarity and similarity.get("status") == "success":
            response["recommendations"] = similarity.get("data", {}).get("recommendations", [])
        # Recommendation Engine
        recom_out = tool_outputs.get("recommendation_engine")
        if recom_out and recom_out.get("status") == "success" and not response.get("recommendations"):
            recs = recom_out.get("data", {}).get("recommendations", [])
            response["recommendations"] = [
                {
                    "title": r.get("title"), 
                    "year": r.get("year"), 
                    "imdb_id": r.get("imdb_id"),
                    "poster_url": f"https://image.tmdb.org/t/p/w200{r.get('poster_path')}" if r.get("poster_path") else ""
                }
                for r in recs
            ]


        archive = tool_outputs.get("archive")
        if archive and archive.get("status") == "success":
            response["download_link"] = archive.get("data", {}).get("download_link", "")
        cinema_search = tool_outputs.get("cinema_search")
        if cinema_search and cinema_search.get("status") == "success":
            results = cinema_search.get("data", {}).get("results", [])
            response["sources"] = [{"title": r.get("title"), "url": r.get("url")} for r in results]
        # Awards from Oscar Award tool
        oscar_out = tool_outputs.get("oscar_award")
        if oscar_out and oscar_out.get("status") == "success":
            awards_data = oscar_out.get("data", {})
            response["awards"] = {
                "oscar_wins": awards_data.get("wins", []),
                "oscar_nominations": awards_data.get("nominations", []),
            }
            

            
        # Filmography Data (Now primarily from TMDB)
        if tmdb_out and tmdb_out.get("status") == "success":
            data = tmdb_out.get("data", {})
            if "filmography_by_role" in data:
                response["filmography"] = data.get("filmography_by_role", {})
                
        # Wikipedia Metadata Integration
        wiki = tool_outputs.get("wikipedia")
        if wiki and wiki.get("status") == "success":
            wdata = wiki.get("data", {})
            wmeta = wdata.get("metadata", {})
            
            # Enrich missing basics
            if not response["poster_url"]:
                response["poster_url"] = wmeta.get("main_thumbnail", "")
            if not response["title"]:
                response["title"] = wdata.get("title", "")
                
            # Add Rich Gallery (images filtered to only contain direct URLs)
            response["image_gallery"] = wmeta.get("image_gallery", {})
            
            # Add Connectivity Links (IMDb, Rotten Tomatoes, etc.)
            response["external_links"] = wmeta.get("external_links", {})
            
            # Add all structured sections for UI display
            response["wikipedia_sections"] = wdata.get("structured_sections", {})
            
            # Merge Awards (Add Wikipedia summary highlights to the existing awards)
            w_awards = wdata.get("structured_sections", {}).get("Awards & Accolades")
            if w_awards:
                if "wikipedia_highlight" not in response["awards"]:
                    response["awards"]["wikipedia_highlight"] = w_awards

        return response

    def _profile_to_dict(self, profile) -> Dict[str, Any]:
        return {
            "region": getattr(profile, "region", None),
            # Aligned with frontend personalization form field names
            "platforms": getattr(profile, "platforms", None),
            "genres": getattr(profile, "genres", None),
            "fav_movies": getattr(profile, "fav_movies", None),
            "fav_actors": getattr(profile, "fav_actors", None),
            "fav_directors": getattr(profile, "fav_directors", None),
        }

    # ─── LLM Report Writer ────────────────────────────────────────────────

    # Phase 18: Move reports to a dedicated logs/ folder to prevent uvicorn reloads
    _LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
    _REPORT_PATH = _LOG_DIR / "llm_report_v2.md"

    def _write_llm_report(
        self, trace: dict[str, Any], response: dict[str, Any]
    ) -> None:
        """Append a structured run entry to llm_report.md."""
        try:
            # Ensure the logs directory exists
            self._LOG_DIR.mkdir(parents=True, exist_ok=True)
            
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            msg = trace.get("message", "")
            resolved = trace.get("resolved_message", msg)

            # ── Intent ──
            intent = trace.get("intent", {})
            primary = intent.get("primary_intent", "UNKNOWN")
            confidence = intent.get("confidence", "?")
            entities = intent.get("entities", [])

            # ── Routing ──
            routing = trace.get("tool_selector", {})
            required_tools = routing.get("required", [])
            optional_tools = routing.get("optional", [])

            # ── Tool execution ──
            tool_exec = trace.get("tool_execution", {})
            cache_hits = tool_exec.get("cache_hits", [])
            cache_misses = tool_exec.get("cache_misses", [])
            timings = tool_exec.get("tool_timings", [])

            # ── Build report ──
            lines: list[str] = []
            lines.append(f"# LLM Backend Report")
            lines.append(f"")
            lines.append(f"## Run - {now}")
            
            # Metadata
            elapsed_ms = int((time.time() - trace.get("_start_time", time.time())) * 1000)
            lines.append(f"- **Total Time**: {elapsed_ms}ms")
            lines.append(f"- **Total LLM Calls**: {trace.get('total_llm_calls', '?')}")
            lines.append(f'- **Query**: "{msg}"')
            if resolved != msg:
                lines.append(f'- **Resolved**: "{resolved}"')
            lines.append(f"")

            # Adaptive Intent Classification
            lines.append(f"### Adaptive Intent Classification")
            
            # Classification Info
            intent_data = trace.get("intent", {})
            domain = intent_data.get("domain", "N/A")
            sec_domain = intent_data.get("secondary_domain")
            category_str = f"{domain}" + (f" (Secondary: {sec_domain})" if sec_domain else "")
            
            lines.append(f"- **Domain/Category**: {category_str}")
            lines.append(f"- **Primary**: {primary} (confidence: {confidence})")
            
            secondary_intents = intent_data.get("secondary_intents", [])
            if secondary_intents:
                lines.append(f"- **Secondary Intents**: {', '.join(secondary_intents)}")

            if entities:
                ent_str = ", ".join(
                    f'{e.get("type","?")}: {e.get("value","?")}'
                    for e in entities if isinstance(e, dict)
                )
                lines.append(f"- **Entities**: [{ent_str}]")

            # Temporal and Knowledge Strategy (Unified Agent)
            kss = intent_data.get("knowledge_source_strategy")
            temporal = intent_data.get("temporal_note")
            if kss:
                lines.append(f"- **Source Strategy**: `{kss}`")
            if temporal:
                lines.append(f"- **Temporal Rules**: {temporal}")
            
            # C.4 Shadow Mode results
            shadow = trace.get("shadow_intent")
            if shadow:
                lines.append(f"- **Shadow Mode (Hybrid)**: domain={shadow.get('domain')}, intent={shadow.get('intent')}, confidence={shadow.get('confidence')}")
                lines.append(f"- **Agreement**: {'✅ YES' if shadow.get('agreeable') else '❌ NO'}")
            lines.append(f"")

            # Backend flow
            lines.append(f"### Backend Flow")
            lines.append(f"- API/Engine Entry: ConversationEngine.run(session_id, user_id, message)")
            lines.append(f"- Intent Classification: {primary}")
            if trace.get("entity_resolution"):
                er = trace["entity_resolution"]
                lines.append(f"- Entity Resolution: {er.get('entity_type','?')} = {er.get('entity_value','?')}")
            lines.append(f"- Routing: required={required_tools}, optional={optional_tools}")
            lines.append(f"- Governance: filter_tool_calls")

            # Tool calls
            approved = trace.get("tool_calls_approved", [])
            rejected = trace.get("tool_calls_rejected", [])
            approved_names = [c.get("name", "?") for c in approved if isinstance(c, dict)]
            rejected_names = [c.get("name", "?") for c in rejected if isinstance(c, dict)]
            lines.append(f"- Tool Calls Approved ({len(approved)}): {approved_names}")
            if rejected:
                lines.append(f"- Tool Calls Rejected ({len(rejected)}): {rejected_names}")
            lines.append(f"- Prompt Build: build_prompt(...)")
            lines.append(f"- LLM Final Response: GroqClient.generate_response(prompt)")
            lines.append(f"- DB: store_message(role='user') + store_message(role='assistant')")
            lines.append(f"")

            # ── Tool Group Selected ──
            sel = trace.get("tool_selector", {})
            source = sel.get("source", "legacy")
            lines.append(f"### Tool Selection ({source.upper()})")
            lines.append(f"| Field | Value |")
            lines.append(f"| :--- | :--- |")
            lines.append(f"| **Entity Type** | {sel.get('entity_type', '?')} |")
            lines.append(f"| **Query Type** | {sel.get('query_type', '?')} |")
            lines.append(f"| **Tool Group** | `{sel.get('tool_group', '?')}` |")
            
            # Show original agent-proposed tools before governance modifications
            agent_tools = intent_data.get("_agent_tools", [])
            if agent_tools:
                t_names = [t.get("name", "?") for t in agent_tools if isinstance(t, dict)]
                lines.append(f"| **Agent Proposed** | {', '.join(f'`{t}`' for t in t_names)} |")

            lines.append(f"| **Final Required Tools** | {', '.join(f'`{t}`' for t in sel.get('required', [])) or 'none'} |")
            if rejected_names:
                lines.append(f"| **Tools Rejected (cap/gov)** | {', '.join(f'`{t}`' for t in rejected_names)} |")
            lines.append(f"")


            # Cache & Timings
            lines.append(f"### Performance & Metadata")
            lines.append(f"- **Cache Hits**: {', '.join(cache_hits) if cache_hits else 'none'}")
            lines.append(f"- **Cache Misses**: {', '.join(cache_misses) if cache_misses else 'none'}")
            lines.append(f"")

            # ── Entity Lifecycle ──
            el = trace.get("entity_lifecycle", {})
            if el:
                lines.append(f"### Entity Lifecycle")

                # Before decay
                pre = el.get("stack_before_decay", [])
                if pre:
                    lines.append(f"**Before this turn (pre-decay):**")
                    lines.append(f"| Entity | Type | Score | Recency |")
                    lines.append(f"| :--- | :--- | :--- | :--- |")
                    for e in pre:
                        lines.append(f"| {e.get('value','?')} | {e.get('type','?')} | {e.get('score','?')} | {e.get('recency','?')} |")
                else:
                    lines.append(f"**Before this turn:** *(empty — fresh session)*")
                lines.append(f"")

                # Added this turn
                added = el.get("added_this_turn", [])
                lines.append(f"**Added/updated this turn:** {', '.join(added) if added else 'none'}")
                lines.append(f"")

                # After
                post = el.get("stack_after", [])
                if post:
                    lines.append(f"**Stack after this turn:**")
                    lines.append(f"| Entity | Type | Role | Score | Recency | Freq |")
                    lines.append(f"| :--- | :--- | :--- | :--- | :--- | :--- |")
                    for e in post:
                        marker = " ← **active**" if e.get("value") in added else ""
                        lines.append(
                            f"| {e.get('value','?')}{marker} "
                            f"| {e.get('type','?')} "
                            f"| {e.get('role','?')} "
                            f"| {e.get('score','?')} "
                            f"| {e.get('recency','?')} "
                            f"| {e.get('frequency','?')} |"
                        )
                else:
                    lines.append(f"**Stack after this turn:** *(empty)*")
                lines.append(f"")

                # Category tracker
                cat = el.get("current_category", "?")
                covered = el.get("covered_categories", [])
                hints = el.get("followup_hints", [])
                lines.append(f"**Query Category:** `{cat}`")
                lines.append(f"**Covered so far:** {', '.join(f'`{c}`' for c in covered) if covered else 'none'}")
                if hints:
                    lines.append(f"**Follow-up hints generated:** {' | '.join(hints)}")
                lines.append(f"")

            lines.append(f"#### Tool Execution Details:")
            if timings:
                for t in timings:
                    line = (
                        f"- **{t['tool']}**: status={t['status']}, {t['execution_time_ms']}ms"
                    )
                    if t.get("error_detail"):
                        line += f", error='{t['error_detail']}'"
                    lines.append(line)
                    # Add snippet for RAG tools
                    if t['tool'] == "rag" and t['status'] == "success":
                        tool_outs = trace.get("tool_outputs", {})
                        rag_out = tool_outs.get(t['tool'], {})
                        passages = rag_out.get("data", {}).get("passages", [])
                        if passages:
                            p = passages[0] # show top passage
                            source_info = p.get('entity_name') or p.get('title') or 'unknown'
                            snippet = p.get('passage', '')[:150].replace('\n', ' ')
                            lines.append(f"  - *Top Snippet* [{source_info}]: {snippet}...")
            else:
                lines.append(f"- none")
            lines.append(f"")

            # Reasoning trace
            if trace.get("reasoning_trace"):
                lines.append(f"### Qwen3 Reasoning Trace")
                lines.append(f"")
                lines.append(f"```text")
                lines.append(trace["reasoning_trace"])
                lines.append(f"```")
                lines.append(f"")

            # Response mode
            lines.append(f"Response Mode: {response.get('response_mode', '?')}")
            lines.append(f"")

            # Session context
            ctx_before = trace.get("session_context_before")
            ctx_after = trace.get("session_context_after")
            if ctx_before or ctx_after:
                lines.append(f"Session Context:")
                if ctx_before:
                    lines.append(f"- Before: last_movie={ctx_before.get('last_movie')}, "
                                 f"last_person={ctx_before.get('last_person')}, "
                                 f"last_entity={ctx_before.get('last_entity')}, "
                                 f"last_intent={ctx_before.get('last_intent')}")
                if ctx_after:
                    lines.append(f"- After:  last_movie={ctx_after.get('last_movie')}, "
                                 f"last_person={ctx_after.get('last_person')}, "
                                 f"last_entity={ctx_after.get('last_entity')}, "
                                 f"last_intent={ctx_after.get('last_intent')}")
                lines.append(f"")

            # Exact response
            lines.append(f"Factual Usage (Phase 10):")
            lines.append(f"- Prompt (Reading): {trace.get('prompt_tokens')} tokens")
            lines.append(f"- Completion (Writing): {trace.get('completion_tokens')} tokens")
            lines.append(f"- Total LLM Calls: {trace.get('total_llm_calls')}")
            if trace.get("token_breakdown"):
                lines.append(f"- Breakdown: {json.dumps(trace.get('token_breakdown'))}")
            lines.append(f"")

            lines.append(f"**Exact Response (Summary):**")
            lines.append(f"```json")
            
            # Make a lightweight copy to avoid dumping 10,000 lines of Wikipedia text to the log
            light_response = dict(response)
            if "wikipedia_sections" in light_response:
                light_response["wikipedia_sections"] = "[...Omitted from logs for brevity...]"
            if "image_gallery" in light_response:
                light_response["image_gallery"] = f"[{len(light_response['image_gallery'])} images omitted]"
            if "awards" in light_response and isinstance(light_response["awards"], dict):
                if "wikipedia_highlight" in light_response["awards"]:
                    light_response["awards"]["wikipedia_highlight"] = "[...Omitted...]"
                    
            lines.append(json.dumps(light_response, indent=2, ensure_ascii=False))
            lines.append(f"```")
            lines.append(f"")

            if trace.get("fatal_error"):
                lines.append(f"### FATAL ERROR")
                lines.append(f"```python")
                lines.append(str(trace.get("fatal_error")))
                lines.append(str(trace.get("fatal_error_tb")))
                lines.append(f"```")
                lines.append(f"")

            report_text = "\n".join(lines)
            with open(self._REPORT_PATH, "a", encoding="utf-8") as f:
                f.write(report_text + "\n")

            self.logger.info("LLM report appended to %s", self._REPORT_PATH)
        except Exception:
            self.logger.exception("Failed to write LLM report")

        # Also persist the full trace to SQLite for admin review
        try:
            elapsed_ms = int((time.time() - trace.get("_start_time", time.time())) * 1000)
            log_request(
                trace, 
                response, 
                total_time_ms=elapsed_ms,
                prompt_tokens=trace.get("prompt_tokens"),
                completion_tokens=trace.get("completion_tokens"),
                token_breakdown=trace.get("token_breakdown"),
                llm_call_count=trace.get("total_llm_calls"),
                tool_outputs=trace.get("tool_outputs")
            )
            
            # Phase 10: Automatically refresh the central token usage report
            try:
                try:
                    from app import check_db_stats  # works under uvicorn (app is on sys.path)
                except ImportError:
                    import check_db_stats  # fallback for CLI / direct execution
                report_file = os.path.join(str(self._LOG_DIR), "token_usage_report.md")
                check_db_stats.generate_full_report(output_path=report_file)
            except Exception as e:
                self.logger.warning("Failed to auto-refresh token usage report: %s", e)
                
        except Exception:
            self.logger.exception("Failed to write RequestLog")

    def _update_caches(self, outputs: Dict[str, Dict]) -> None:
        db = SessionLocal()
        try:
            imdb_output = outputs.get("imdb")
            wiki_output = outputs.get("wikipedia")
            if imdb_output and imdb_output.get("status") == "success":
                title = imdb_output.get("data", {}).get("title")
                imdb_data = imdb_output.get("data", {})
                wiki_data = {}
                if wiki_output and wiki_output.get("status") == "success":
                    wiki_data = wiki_output.get("data", {})
                if title:
                    set_metadata_cache(db, title, imdb_data, wiki_data)

            watchmode = outputs.get("watchmode")
            if watchmode and watchmode.get("status") == "success":
                title = watchmode.get("data", {}).get("title")
                region = watchmode.get("data", {}).get("region")
                if title and region:
                    set_streaming_cache(db, title, region, watchmode.get("data", {}))

            similarity = outputs.get("similarity")
            if similarity and similarity.get("status") == "success":
                title = similarity.get("data", {}).get("title")
                if title:
                    set_similarity_cache(db, title, similarity.get("data", {}))
        finally:
            db.close()

