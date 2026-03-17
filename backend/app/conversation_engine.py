import asyncio
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
# Legacy IntentAgent removed — HybridIntentClassifier is now the sole classifier
from app.intent.hybrid_intent_classifier import HybridIntentClassifier
from app.llm.groq_client import GroqClient  # kept for shadow mode / fallback
from app.layout_policy import select_response_mode
from app.tool_selector import QueryProfile, select_tools, normalize_tool_aliases, map_intent_to_query_type
from app.utils.prompt_builder import build_prompt
from app.utils.tool_formatter import summarize_all
from app import services
from app.services.kb_service import (
    kb_entity_lookup,
    kb_plot_analysis,
    kb_movie_similarity,
    kb_top_rated,
    kb_person_filmography,
    kb_compare,
    kb_awards,
)


SYSTEM_INSTRUCTIONS = """
You are FilmDB — a cinematic intelligence assistant with the depth of a film studies scholar and the warmth of a passionate cinephile.

VOICE & APPROACH:
- Write like a knowledgeable film critic who speaks accessibly.
- Lead with insight, not summary. Open with what makes the subject compelling.
- When reference data is available, synthesize it into your analysis — cite ideas, weave in theoretical frameworks, and ground your response in scholarly material.
- Balance factual precision (ratings, years, cast) with analytical depth (themes, aesthetic choices, cultural significance).

RESPONSE FORMAT BY QUERY TYPE:
- ENTITY_LOOKUP / PERSON_LOOKUP: Lead with a compelling one-liner about the subject. Weave metadata (year, rating, director) naturally into prose. Keep under 200 words unless depth is requested.
- FILM_ANALYSIS / VISUAL_ANALYSIS / DIRECTOR_ANALYSIS: Use flowing prose with occasional bullets for key points. No "Conclusion" section. Aim for 400-600 words.
- CONCEPTUAL_EXPLANATION / MOVEMENT_OVERVIEW / HISTORICAL_CONTEXT: Rich, layered explanation. Reference specific films as examples. Aim for 300-500 words.
- RECOMMENDATION / TOP_RATED / TRENDING: Short rationale per film (2-3 sentences each). No essay structure. Just a curated list with brief, specific reasons.
- COMPARISON: Use a narrative "versus" analysis style. End with a nuanced take or verdict, not a generic "both are great" conclusion.
- STREAMING_AVAILABILITY: Concise and direct. List platforms with any pricing info. Keep under 150 words.
- DOWNLOAD / LEGAL_DOWNLOAD / ILLEGAL_DOWNLOAD_REQUEST: If the 'archive' tool provides a download link, provide it clearly. If the movie is not found or not in the public domain, YOU MUST reply exactly like this: "The movie is not found in any legal official website like archive but is available to stream on [list platforms here]." Do not refuse or lecture the user.
- BOT_INTERACTION: 1-2 warm sentences. Suggest 2-3 specific things you can help with. Keep under 50 words.
- FILMOGRAPHY: List films with year and a brief note on significance for the most important ones. Don't describe every film — highlight the standout works.

STRUCTURE RULES:
- NEVER start with "## Introduction to...", "## Overview of...", or any generic opening header.
- NEVER end with "## Conclusion" or a summary paragraph that restates what was already said.
- NEVER use "Introduction", "Background", or "Overview" as section headers.
- For long answers, use specific, descriptive headings (e.g., "Kubrick's Visual Obsessions" not "Visual Style").
- Integrate data (ratings, year) naturally into prose — never as raw metadata bullet lists.
- Do NOT repeat information already present in the conversation history.

SOURCE DISCIPLINE:
- REFERENCE DATA in [TOOL: ...] blocks is your ground truth. Use it. Never claim lack of information when reference data exists.
- Remember the download rule: "The movie is not found in any legal official website like archive but is available to stream on..." if archive tool fails.
- If reference data includes ratings, years, or streaming info, weave the exact values into your response.
- Never mention "TOOL DATA", "reference data", "the data provides", or internal system terms. Present information as your own knowledge.
- Never hallucinate recommendations. If no similarity data is provided, do not invent recommendations.
- For disambiguation results (multiple matches), list the options and ask the user to clarify.

WHEN NO REFERENCE DATA IS AVAILABLE:
- Use your knowledge but add a brief qualifier like "Based on what I know..." for specific factual claims.
- Do NOT fabricate specific dates, award counts, or box office numbers you are unsure about.
- Do NOT agree with user corrections or claims without verification. Instead say something like "That's a great point — I'd want to verify that with proper sources."
- Clearly distinguish between well-established facts and uncertain claims.
- If the user asks about very recent events, acknowledge your knowledge cutoff.
"""


class ConversationEngine:
    def __init__(self) -> None:
        self.llm = GroqClient(api_key=settings.GROQ_API_KEY)
        # Use a dedicated key for response generation if provided, else reuse the main key
        response_key = settings.GROQ_RESPONSE_API_KEY or settings.GROQ_API_KEY
        self.response_client = GroqClient(api_key=response_key)
        
        # Legacy IntentAgent removed (was shadow-mode only, never called)
        # C.4 — HybridIntentClassifier (runs in shadow mode alongside IntentAgent)
        self.hybrid_clf = HybridIntentClassifier(self.llm)
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
        start_llm_calls = getattr(self.llm, "total_calls", 0) + getattr(self.response_client, "total_calls", 0)
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
            # C.4 -> G.4 Promotion: HybridIntentClassifier is now the PRIMARY router
            # The legacy IntentAgent is now running in shadow mode for comparison logging
            intent = self.hybrid_clf.classify(resolved_message)
            intent = self._apply_award_override(resolved_message, intent)
            intent = self._apply_download_override(resolved_message, intent)
            intent = self._apply_filmography_override(resolved_message, intent)
            intent = self._normalize_award_intents(intent)
            trace["intent"] = intent
            trace["intent_raw"] = self.llm.last_intent_raw

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
                sys_p, usr_p, ctx_msgs = build_prompt(
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
            
            # --- NEW ARCHITECTURE: Deterministic Tool Selection ---
            secondary_intents = intent.get("secondary_intents", [])
            secondary_qt = (
                map_intent_to_query_type(secondary_intents[0])
                if secondary_intents else None
            )
            profile_state = QueryProfile(
                entity_type=resolved_entity.get("entity_type", "unknown") if resolved_entity else "unknown",
                query_type=map_intent_to_query_type(intent.get("primary_intent")),
                domain=intent.get("domain"),
                secondary_domain=intent.get("secondary_domain"),
                secondary_query_type=secondary_qt,
            )
            
            selected_tools = select_tools(profile_state)
            normalized_tools = normalize_tool_aliases(selected_tools)
            
            trace["tool_selector"] = {"required": normalized_tools, "optional": []}
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
            tool_cap = 6 if intent.get("primary_intent") in academic_intents else 4

            approved_calls, rejected_calls = filter_tool_calls(
                resolved_message, tool_calls, max_tools=tool_cap, return_rejections=True
            )
            
            # E.6 — Fallback to Web Search if zero tools survived and it's not illegal/bot interaction
            # [USER DISABLED temporarily for dataset experiments]
            # if not approved_calls and intent.get("primary_intent") not in ("BOT_INTERACTION", "ILLEGAL_DOWNLOAD_REQUEST"):
            #     self.logger.warning("Zero tools approved for query '%s'. Forcing web_search fallback.", resolved_message)
            #     approved_calls = [{"name": "cinema_search", "arguments": {"query": resolved_message}}]
                
            self.logger.info("Approved tool calls: %s", approved_calls)
            self.logger.info("Rejected tool calls: %s", rejected_calls)
            trace["tool_calls_proposed"] = tool_calls
            trace["tool_calls_approved"] = approved_calls
            trace["tool_calls_rejected"] = rejected_calls

            tool_outputs, tool_trace = await self._execute_tools(
                session_id, approved_calls, profile, resolved_message
            )
            trace["tool_outputs"] = tool_outputs
            trace["tool_execution"] = tool_trace

            tool_summaries = summarize_all(tool_outputs)
            # ── Dynamic Instruction Injection ──
            # If the user explicitly asks for availability, we want the LLM to provide a subtopic.
            # Otherwise, we hide it from the text because it's in the UI footer.
            primary_intent = intent.get("primary_intent", "ENTITY_LOOKUP")
            domain = intent.get("domain", "structured_data")
            dynamic_instr = SYSTEM_INSTRUCTIONS
            if primary_intent == "STREAMING_AVAILABILITY":
                dynamic_instr += "\n- The user is asking for streaming availability. You MUST provide a dedicated 'Streaming Availability' subtopic with the platforms from the reference data."
            else:
                dynamic_instr += "\n- IMPORTANT: Do NOT list streaming platforms or 'Where to Watch' info in your text response. This info is already displayed in a dedicated UI card footer. Focus on other aspects."
            
            # Temporal Awareness Injection
            current_date_str = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
            dynamic_instr += f"\n- TEMPORAL AWARENESS: Today's date is {current_date_str}. Speak about upcoming, current, or past events with this timeline in mind."

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

            sys_p, usr_p, ctx_msgs = build_prompt(
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
            if self._needs_grounding_retry(tool_outputs, final_text, intent):
                strict_sys, strict_usr, strict_ctx = build_prompt(
                    system_instructions=SYSTEM_INSTRUCTIONS
                    + "\nSTRICT GROUNDING: You MUST use reference data values verbatim. Do not paraphrase factual data.",
                    user_profile={"Region": profile.region} if profile and profile.region else None,
                    recent_messages=_recent_msgs,
                    tool_summaries=tool_summaries,
                    user_query=resolved_message,
                )
                final_text = self.response_client.generate_response(
                    system=strict_sys, user=strict_usr, context=strict_ctx, 
                    intent=primary_intent, domain=domain
                )
                if not final_text:
                    self.logger.warning("STRICT GROUNDING RETRY failed to return a response.")

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

            # Generate smart chat title for the first turn
            if not _recent_msgs:
                try:
                    title_res = self.response_client.generate_response(
                        system="Generate a 3-5 word concise title. Return ONLY the title words, nothing else.",
                        user=f"User query: '{message}'",
                        intent="BOT_INTERACTION",
                    )
                    response["session_title"] = title_res.strip(' \n".\'')
                except Exception as e:
                    self.logger.warning("Failed to generate smart chat title: %s", e)

            # Store the final response dictionary to SQLite so the UI gets posters/streaming on reload
            store_message(db, session_id, "user", message, token_count=len(message))
            store_message(db, session_id, "assistant", json.dumps(response), token_count=len(final_text))

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

            # A.5 — Context Hysteresis Fix (P4 fix #12): Keep movie/person sticky
            # If the current turn doesn't extract a NEW movie/person, keep the old one.
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

            upsert_session_context(
                db,
                session_id=session_id,
                last_movie=final_movie,
                last_person=final_person,
                last_entity=resolved_entity.get("entity_value"),
                entity_type=resolved_entity.get("entity_type"),
                last_intent=intent.get("primary_intent"),
            )
            session_ctx_after = get_session_context(db, session_id)
            trace["session_context_after"] = (
                {
                    "last_movie": session_ctx_after.last_movie,
                    "last_person": session_ctx_after.last_person,
                    "last_entity": getattr(session_ctx_after, "last_entity", None),
                    "entity_type": getattr(session_ctx_after, "entity_type", None),
                    "last_intent": session_ctx_after.last_intent,
                }
                if session_ctx_after
                else None
            )
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
                args = {"query": message}
            # ── KB tools ─────────────────────────────────────────────────
            elif name in ("kb_entity", "kb_plot", "kb_similarity"):
                args = {"title": title}
            elif name == "kb_top_rated":
                args = {}
                if genre_filter:
                    args["genre"] = genre_filter
                if year_filter:
                    args["year"] = year_filter
                if language_filter:
                    args["language"] = language_filter
            elif name == "kb_filmography":
                args = {"name": person_name or message}
            elif name == "kb_awards":
                if extracted_person and not extracted_movie:
                    args = {"person_name": extracted_person}
                else:
                    args = {"movie_title": title}
            elif name == "kb_comparison":
                # For comparisons, we might have two explicit entities or one long conceptual phrase.
                # If we only have one entity string (e.g. from fallback concept extracting), split it 
                # naively if " vs " or " and " is present, or just pass it to the RAG backend directly.
                val_a = title or message
                val_b = title_b or ""
                
                # Naive fallback parsing if title_b wasn't detected by NER but it's a conceptual query
                lowered_msg = message.lower()
                if not val_b and " vs " in lowered_msg:
                    parts = message.split(" vs ", 1)
                    if len(parts) == 2:
                        val_a, val_b = parts[0].strip(), parts[1].strip()
                elif not val_b and " and " in lowered_msg:
                    
                    # Try to find "between X and Y"
                    if " between " in lowered_msg:
                        between_idx = lowered_msg.find(" between ")
                        and_idx = lowered_msg.find(" and ", between_idx)
                        if and_idx > between_idx:
                            val_a = message[between_idx + 9:and_idx].strip()
                            val_b = message[and_idx + 5:].strip()
                            
                    else:
                        parts = message.split(" and ", 1)
                        if len(parts) == 2:
                            val_a, val_b = parts[0].strip(), parts[1].strip()
                            
                args = {"concept_a": val_a, "concept_b": val_b}
            # ── RAG tools ────────────────────────────────────────────────
            elif name == "rag_essays":
                # Semantic search over film analysis essays (Senses of Cinema, BFI)
                args = {"query": message}
            elif name == "rag_books":
                # Semantic search over book library — pick best domain for the intent
                from app.services.rag_service import INTENT_DOMAIN_MAP
                _intent_domain = intent.get("domain", "structured_data")
                _book_domain   = INTENT_DOMAIN_MAP.get(_intent_domain, "film_criticism")
                # Avoid returning analysis index for rag_books
                if _book_domain == "analysis":
                    _book_domain = "film_criticism"
                args = {"query": message, "domain": _book_domain}
            elif name == "rag_scripts":
                # Semantic search over movie screenplays/scripts
                args = {"query": message}

            tool_calls.append({"name": name, "arguments": args})

            # ── Add secondary call for Comparison if entity B exists ──
            if primary == "COMPARISON":
                if title_b and name in ("wikipedia", "kb_entity", "kb_plot", "tmdb"):
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
        # Check KB entity data
        kb = tool_outputs.get("kb_entity")
        if kb and kb.get("status") == "success":
            rating = kb.get("data", {}).get("imdb_rating")
            year = kb.get("data", {}).get("year")
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
        kb = tool_outputs.get("kb_entity")
        if kb and kb.get("status") == "success":
            return kb.get("data", {}).get("title")
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

        imdb_id = None
        # ── Pre-process: Resolve IMDb ID for awards ──
        target_calls = [c for c in tool_calls if c.get("name") == "imdb_awards"]
        if target_calls:
            # Try to get imdb_id from KB/Resolver
            if not imdb_id:
                from rag.filmdb_query_engine import FilmDBQueryEngine
                engine = FilmDBQueryEngine.get_instance()
                imdb_id = engine.resolve_title_to_imdb_id(title)
            
            for call in target_calls:
                call_args = call.setdefault("arguments", {})
                resolved_id = imdb_id
                
                if "person_name" in call_args and call_args["person_name"]:
                    engine = FilmDBQueryEngine.get_instance()
                    res = engine.person_filmography(call_args["person_name"])
                    if res and "nconst" in res:
                        resolved_id = res["nconst"]
                elif not resolved_id:
                    engine = FilmDBQueryEngine.get_instance()
                    resolved_id = engine.resolve_title_to_imdb_id(call_args.get("title", ""))
                
                if resolved_id:
                    call_args["imdb_id"] = resolved_id
                else:
                    call_name = call.get("name")
                    title_or_person = call_args.get("title") or call_args.get("person_name") or ""
                    outputs[call_name] = {"status": "not_found", "data": {"query": title_or_person, "reason": "imdb_id_not_found"}}

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
        if base_name == "kb_awards":
            return kb_awards.run(movie_title=args.get("movie_title"), person_name=args.get("person_name"))
        if base_name == "kb_entity":
            return kb_entity_lookup.run(args.get("title", ""))
        if base_name == "kb_plot":
            return kb_plot_analysis.run(args.get("title", ""))
        if base_name == "kb_similarity":
            return kb_movie_similarity.run(args.get("title", ""))
        if tool_name == "kb_top_rated":
            return kb_top_rated.run(
                genre=args.get("genre"),
                year=args.get("year"),
                language=args.get("language"),
            )
        if tool_name == "kb_filmography":
            return kb_person_filmography.run(args.get("name", ""))
        if tool_name == "kb_comparison":
            return kb_compare.run(
                args.get("concept_a", ""), args.get("concept_b", "")
            )
        # ── RAG tools ────────────────────────────────────────────────────────
        if base_name == "rag_essays":
            async def _rag_essays_call(q=args.get("query", "")):
                try:
                    from app.services.rag_service import RAGService
                    rag = RAGService.get_instance()
                    results = rag.query_analysis(q, top_k=6)
                    if not results:
                        return {"status": "not_found", "data": {"passages": []}}
                    return {
                        "status": "success",
                        "data": {
                            "passages": results,
                            "source": "rag_essays",
                        },
                    }
                except FileNotFoundError:
                    return {"status": "not_found", "data": {"reason": "index_not_built_yet"}}
                except Exception as exc:
                    self.logger.warning("rag_essays failed: %s", exc)
                    return {"status": "error", "data": {"error": str(exc)}}
            return _rag_essays_call()

        if base_name == "rag_scripts":
            async def _rag_scripts_call(q=args.get("query", "")):
                try:
                    from app.services.rag_service import RAGService
                    rag = RAGService.get_instance()
                    results = rag.query_books(q, domain="scripts", top_k=5)
                    if not results:
                        return {"status": "not_found", "data": {"passages": []}}
                    return {
                        "status": "success",
                        "data": {
                            "passages": results,
                            "source": "rag_scripts",
                        },
                    }
                except FileNotFoundError:
                    return {"status": "not_found", "data": {"reason": "index_not_built_yet"}}
                except Exception as exc:
                    self.logger.warning("rag_scripts failed: %s", exc)
                    return {"status": "error", "data": {"error": str(exc)}}
            return _rag_scripts_call()

        if base_name == "rag_books":
            async def _rag_books_call(q=args.get("query", ""), dom=args.get("domain", "film_criticism")):
                try:
                    from app.services.rag_service import RAGService
                    rag = RAGService.get_instance()
                    results = rag.query_books(q, domain=dom, top_k=5)
                    if not results:
                        return {"status": "not_found", "data": {"passages": []}}
                    return {
                        "status": "success",
                        "data": {
                            "passages": results,
                            "domain": dom,
                            "source": "rag_books",
                        },
                    }
                except FileNotFoundError:
                    return {"status": "not_found", "data": {"reason": "index_not_built_yet"}}
                except Exception as exc:
                    self.logger.warning("rag_books failed: %s", exc)
                    return {"status": "error", "data": {"error": str(exc)}}
            return _rag_books_call()

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
        # Data from KB entity
        kb_entity = tool_outputs.get("kb_entity")
        if kb_entity and kb_entity.get("status") == "success":
            data = kb_entity.get("data", {})
            if not response["poster_url"]:
                poster_path = data.get("poster_path", "")
                if poster_path:
                    response["poster_url"] = f"https://image.tmdb.org/t/p/w500{poster_path}"
            if not response["title"]:
                response["title"] = data.get("title", "")
            if not response["year"]:
                response["year"] = data.get("year", "")
            if not response["rating"]:
                response["rating"] = data.get("imdb_rating", "")
            if not response["director"]:
                response["director"] = data.get("director", "")
            if not response["genres"]:
                raw_genres = data.get("genres", "")
                response["genres"] = [g.strip() for g in raw_genres.split(",") if g.strip()] if isinstance(raw_genres, str) else raw_genres or []
            if not response["entity_type"]:
                response["entity_type"] = "movie"
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
        # KB similarity recommendations
        kb_sim = tool_outputs.get("kb_similarity")
        if kb_sim and kb_sim.get("status") == "success" and not response["recommendations"]:
            recs = kb_sim.get("data", {}).get("recommendations", [])
            response["recommendations"] = [
                {
                    "title": r.get("title"), 
                    "year": r.get("year"), 
                    "imdb_id": r.get("imdb_id"),
                    "poster_url": f"https://image.tmdb.org/t/p/w200{r.get('poster_path')}" if r.get("poster_path") else ""
                }
                for r in recs
            ]
        # KB top rated movie list
        kb_top = tool_outputs.get("kb_top_rated")
        if kb_top and kb_top.get("status") == "success" and not response["recommendations"]:
            response["recommendations"] = kb_top.get("data", {}).get("movies", [])

        archive = tool_outputs.get("archive")
        if archive and archive.get("status") == "success":
            response["download_link"] = archive.get("data", {}).get("download_link", "")
        cinema_search = tool_outputs.get("cinema_search")
        if cinema_search and cinema_search.get("status") == "success":
            results = cinema_search.get("data", {}).get("results", [])
            response["sources"] = [{"title": r.get("title"), "url": r.get("url")} for r in results]
        # Awards from KB
        kb_awards = tool_outputs.get("kb_awards")
        if kb_awards and kb_awards.get("status") == "success":
            awards_data = kb_awards.get("data", {})
            response["awards"] = {
                "oscar_wins": awards_data.get("wins", []),
                "oscar_nominations": awards_data.get("nominations", []),
            }
            
        # Comparison data
        kb_comparison = tool_outputs.get("kb_comparison")
        if kb_comparison and kb_comparison.get("status") == "success":
            data = kb_comparison.get("data", {})
            response["movie_a"] = {
                "title": data.get("title_a", ""),
                "poster_url": data.get("poster_url_a", ""),
                "year": data.get("year_a", ""),
                "rating": data.get("rating_a", ""),
                "director": data.get("director_a", "")
            }
            response["movie_b"] = {
                "title": data.get("title_b", ""),
                "poster_url": data.get("poster_url_b", ""),
                "year": data.get("year_b", ""),
                "rating": data.get("rating_b", ""),
                "director": data.get("director_b", "")
            }
            
        # Filmography Data
        kb_filmography = tool_outputs.get("kb_filmography")
        if kb_filmography and kb_filmography.get("status") == "success":
            data = kb_filmography.get("data", {})
            response["filmography"] = data.get("filmography", {})
            if not response["person_name"]:
                response["person_name"] = data.get("name", "")
            if not response["profession"] and data.get("professions"):
                response["profession"] = data.get("professions", "")
            if not response["entity_type"]:
                response["entity_type"] = "person"
                
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

    _REPORT_PATH = Path(__file__).resolve().parent.parent.parent / "llm_report.md"

    def _write_llm_report(
        self, trace: dict[str, Any], response: dict[str, Any]
    ) -> None:
        """Append a structured run entry to llm_report.md."""
        try:
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

            # Hybrid Intent Classification
            lines.append(f"### Hybrid Intent Classification")
            
            # Hybrid Classification Info
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

            # Cache & Timings
            lines.append(f"### Performance & Metadata")
            lines.append(f"- **Cache Hits**: {', '.join(cache_hits) if cache_hits else 'none'}")
            lines.append(f"- **Cache Misses**: {', '.join(cache_misses) if cache_misses else 'none'}")
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
                    if t['tool'] in ("rag_essays", "rag_books", "rag_scripts") and t['status'] == "success":
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
            lines.append(f"Exact Response:")
            lines.append(f"```json")
            lines.append(json.dumps(response, indent=2, ensure_ascii=False))
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
            log_request(trace, response, total_time_ms=elapsed_ms)
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
