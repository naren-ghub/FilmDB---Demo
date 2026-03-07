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
    get_similarity_cache,
    get_streaming_cache,
    set_metadata_cache,
    set_similarity_cache,
    set_streaming_cache,
)
from app.db.session_store import (
    get_or_create_session,
    get_or_create_user,
    get_session_context,
    get_user_profile,
    store_message,
    store_tool_call,
    upsert_session_context,
)
from app.governance import filter_tool_calls
from app.guardrails import should_block
from app.entity_resolver import EntityResolver
from app.intent_agent import IntentAgent
from app.llm.groq_client import GroqClient
from app.layout_policy import select_response_mode
from app.routing_matrix import build_tool_plan
from app.utils.prompt_builder import build_prompt
from app.utils.tool_formatter import summarize_all
from app import services
from app.services.kb import (
    kb_entity_lookup,
    kb_plot_analysis,
    kb_critic_summary,
    kb_movie_similarity,
    kb_top_rated,
    kb_person_filmography,
    kb_movie_comparison,
)


SYSTEM_INSTRUCTIONS = """
You are FilmDB, a cinematic intelligence assistant. Your role:
- Provide detailed, structured, insightful responses.
- Expand intelligently when useful.
- Be analytical and thoughtful.
- Personalize recommendations when user preferences are provided.
- Respond warmly and helpfully to greetings and casual conversation.

Rules:
- NEVER start your response with "Introduction to...". Dive straight into the answer using a direct, engaging tone. Do not use generic document headers like "Introduction".
- Use provided tool data as factual ground truth.
- Do not fabricate streaming, rating, or download information.
- You MUST rely on TOOL DATA as factual ground truth. If TOOL DATA exists, do not claim lack of information.
- If TOOL DATA includes rating, year, or streaming data, you MUST include the exact values in the response.
- TOOL DATA is provided in [TOOL_DATA] ... [/TOOL_DATA] blocks.
- If live data is provided, integrate it naturally into your response.
- If no tool data is available, use your knowledge but mention that live data could provide more accurate details.
- Structure responses using headings and bullet points when appropriate, but skip generic introductory headers.
- For greetings, respond warmly and suggest what you can help with (movie info, streaming, recommendations, etc.)
"""


TOOL_PROPOSAL_SYSTEM = ""
TOOL_PROPOSAL_USER = ""


class ConversationEngine:
    def __init__(self) -> None:
        self.llm = GroqClient()
        self.intent_agent = IntentAgent(self.llm)
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
        trace: dict[str, Any] = {
            "session_id": session_id,
            "user_id": user_id,
            "message": message,
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

            intent = self.intent_agent.classify(resolved_message)
            intent = self._apply_award_override(resolved_message, intent)
            intent = self._apply_download_override(resolved_message, intent)
            trace["intent"] = intent
            trace["intent_raw"] = self.llm.last_intent_raw
            resolved_entity = self.entity_resolver.resolve(resolved_message, intent)
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
                    db, session_id, "assistant", block_reason, token_count=len(block_reason)
                )
                trace["response_mode"] = response["response_mode"]
                trace["final_text"] = block_reason
                self._write_llm_report(trace, response)
                return response, trace

            # ── Handle greetings as a fast path (no tools needed) ──
            if intent.get("primary_intent") == "GREETING":
                prompt = build_prompt(
                    system_instructions=SYSTEM_INSTRUCTIONS,
                    user_profile=self._profile_to_dict(profile) if profile else None,
                    recent_messages=[],
                    tool_summaries=[],
                    user_query=resolved_message,
                )
                greeting_text = self.llm.generate_response(prompt)
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
                store_message(db, session_id, "assistant", greeting_text, token_count=len(greeting_text))
                trace["response_mode"] = response["response_mode"]
                trace["final_text"] = greeting_text
                self._write_llm_report(trace, response)
                return response, trace

            trace["planner_raw"] = None
            trace["planner"] = None
            routing = build_tool_plan(intent, [])
            trace["routing_matrix"] = routing
            tool_calls = self._build_tool_calls(
                routing["required"] + routing["optional"],
                resolved_message,
                intent,
                resolved_entity,
                profile,
            )
            tool_calls = self._apply_download_policy(tool_calls, intent, resolved_entity)
            approved_calls, rejected_calls = filter_tool_calls(
                resolved_message, tool_calls, max_tools=4, return_rejections=True
            )
            self.logger.info("Approved tool calls: %s", approved_calls)
            self.logger.info("Rejected tool calls: %s", rejected_calls)
            trace["tool_calls_proposed"] = tool_calls
            trace["tool_calls_approved"] = approved_calls
            trace["tool_calls_rejected"] = rejected_calls

            tool_outputs, tool_trace = await self._execute_tools(
                session_id, approved_calls, profile, resolved_message
            )
            trace["tool_execution"] = tool_trace

            tool_summaries = summarize_all(tool_outputs)
            prompt = build_prompt(
                system_instructions=SYSTEM_INSTRUCTIONS,
                user_profile=self._profile_to_dict(profile) if profile else None,
                recent_messages=[],
                tool_summaries=tool_summaries,
                user_query=resolved_message,
            )

            final_text = self.llm.generate_response(prompt)
            if self._needs_grounding_retry(tool_outputs, final_text):
                strict_prompt = build_prompt(
                    system_instructions=SYSTEM_INSTRUCTIONS
                    + "\nSTRICT GROUNDING: You MUST use TOOL DATA values verbatim.",
                    user_profile=self._profile_to_dict(profile) if profile else None,
                    recent_messages=[],
                    tool_summaries=tool_summaries,
                    user_query=resolved_message,
                )
                final_text = self.llm.generate_response(strict_prompt)
            if not final_text:
                final_text = "I can help with movie details, streaming availability, and recommendations."
            trace["final_text"] = final_text

            store_message(db, session_id, "user", message, token_count=len(message))
            store_message(db, session_id, "assistant", final_text, token_count=len(final_text))

            response_mode = select_response_mode(
                intent.get("primary_intent", "ENTITY_LOOKUP"),
                intent.get("secondary_intents", []),
                tool_outputs,
            )
            response = self._build_response(final_text, tool_outputs)
            response["response_mode"] = response_mode
            trace["response_mode"] = response_mode

            upsert_session_context(
                db,
                session_id=session_id,
                last_movie=self._extract_movie_from_tools(tool_outputs),
                last_person=self._extract_person_from_intent(intent)
                or (
                    resolved_entity.get("entity_value")
                    if resolved_entity.get("entity_type") == "person"
                    else None
                ),
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
            self._write_llm_report(trace, response)
            return response, trace
        finally:
            db.close()

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
        title = resolved_entity.get("entity_value") or message
        if resolved_entity.get("entity_type") == "person":
            person_name = resolved_entity.get("entity_value") or message
        else:
            person_name = self._extract_person_from_intent(intent) or message
        region = None
        if profile and getattr(profile, "region", None):
            region = profile.region

        # Extract second entity for comparison
        title_b = None
        primary = intent.get("primary_intent", "")
        if primary == "COMPARISON":
            entities = intent.get("entities", [])
            movie_entities = [e for e in entities if isinstance(e, dict) and e.get("type") == "movie"]
            if len(movie_entities) >= 2:
                title = movie_entities[0].get("value", title)
                title_b = movie_entities[1].get("value", "")

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
            if name in ("imdb", "wikipedia", "similarity", "archive"):
                args = {"title": title}
            elif name == "watchmode":
                args = {"title": title, "region": region or "IN"}
            elif name == "web_search":
                args = {"query": message}
            elif name == "imdb_trending_tamil":
                args = {}
            elif name == "imdb_top_rated_english":
                args = {}
            elif name == "imdb_upcoming":
                args = {"country": region or "IN"}
            elif name == "imdb_person":
                args = {"name": person_name}
            elif name == "rt_reviews":
                args = {"title": title}
            # ── KB tools ─────────────────────────────────────────────────
            elif name in ("kb_entity", "kb_plot", "kb_critic", "kb_similarity"):
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
                args = {"name": person_name}
            elif name == "kb_comparison":
                args = {"title_a": title, "title_b": title_b or ""}
            tool_calls.append({"name": name, "arguments": args})
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
        if any(k in lowered for k in ["oscar", "oscars", "academy awards", "nominations", "best picture"]):
            intent = dict(intent)
            intent["primary_intent"] = "AWARD_LOOKUP"
            intent["confidence"] = 100
        return intent

    def _apply_download_override(self, message: str, intent: dict[str, Any]) -> dict[str, Any]:
        lowered = message.lower()
        if "download" not in lowered:
            return intent
        intent = dict(intent)
        if any(k in lowered for k in ["torrent", "pirated", "cracked", "free download"]):
            intent["primary_intent"] = "ILLEGAL_DOWNLOAD_REQUEST"
            intent["confidence"] = 100
        else:
            intent["primary_intent"] = "LEGAL_DOWNLOAD"
        return intent

    def _apply_download_policy(
        self, tool_calls: list[dict[str, Any]], intent: dict[str, Any], resolved_entity: dict[str, Any]
    ) -> list[dict[str, Any]]:
        primary = intent.get("primary_intent")
        if primary not in ("DOWNLOAD", "LEGAL_DOWNLOAD"):
            return tool_calls
        public_domain = bool(resolved_entity.get("public_domain"))
        if public_domain:
            title = resolved_entity.get("entity_value")
            if title and not any(call.get("name") == "archive" for call in tool_calls):
                tool_calls.append({"name": "archive", "arguments": {"title": title}})
            return tool_calls
        return [call for call in tool_calls if call.get("name") != "archive"]

    def _needs_grounding_retry(self, tool_outputs: dict[str, dict], final_text: str) -> bool:
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
        return False

    def _extract_movie_from_tools(self, tool_outputs: dict[str, dict]) -> str | None:
        imdb = tool_outputs.get("imdb")
        if imdb and imdb.get("status") == "success":
            return imdb.get("data", {}).get("title")
        kb = tool_outputs.get("kb_entity")
        if kb and kb.get("status") == "success":
            return kb.get("data", {}).get("title")
        return None

    def _extract_person_from_intent(self, intent: dict[str, Any]) -> str | None:
        entities = intent.get("entities", [])
        if entities:
            first_entity = entities[0]
            if isinstance(first_entity, dict):
                entity_type = str(first_entity.get("type", "")).lower()
                if entity_type in ("person", "director", "actor", "filmmaker", "creator"):
                    return str(first_entity.get("value"))
                return None
            return str(first_entity)
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
                if region:
                    streaming_cache = get_streaming_cache(db, title, region)
                    if streaming_cache:
                        cached_outputs["watchmode"] = {
                            "status": "success",
                            "data": streaming_cache.streaming_data,
                        }
                        cache_hits.append("watchmode")
                    else:
                        cache_misses.append("watchmode")

                similarity_cache = get_similarity_cache(db, title)
                if similarity_cache:
                    cached_outputs["similarity"] = {
                        "status": "success",
                        "data": similarity_cache.recommendations,
                    }
                    cache_hits.append("similarity")
                else:
                    cache_misses.append("similarity")
        finally:
            db.close()

        outputs: Dict[str, Dict] = dict(cached_outputs)

        similarity_call = next((call for call in tool_calls if call.get("name") == "similarity"), None)
        imdb_call = next((call for call in tool_calls if call.get("name") == "imdb"), None)
        imdb_id = None
        if outputs.get("imdb"):
            imdb_id = outputs["imdb"].get("data", {}).get("imdb_id")

        if similarity_call:
            if not imdb_id and imdb_call and imdb_call.get("name") not in outputs:
                imdb_args = imdb_call.get("arguments", {})
                start = time.monotonic()
                # Use TMDB to get imdb_id for similarity lookup
                tmdb_result = await services.tmdb_service.run(imdb_args.get("title", ""))
                elapsed_ms = int((time.monotonic() - start) * 1000)
                outputs["imdb"] = tmdb_result
                store_tool_call(
                    session_id=session_id,
                    tool_name="imdb",
                    request_payload=imdb_args,
                    response_status=tmdb_result.get("status", "error"),
                    execution_time_ms=elapsed_ms,
                )
                imdb_id = tmdb_result.get("data", {}).get("imdb_id")

            if imdb_id:
                similarity_call.setdefault("arguments", {})["imdb_id"] = imdb_id
            else:
                title = similarity_call.get("arguments", {}).get("title", "")
                outputs["similarity"] = {"status": "not_found", "data": {"title": title}}

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

        start_times = [time.monotonic() for _ in tasks]
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=45.0,
            )
        except asyncio.TimeoutError:
            self.logger.warning("Tool execution timed out after 45s")
            results = [TimeoutError("Tool execution timed out") for _ in tasks]
        timings: list[dict[str, Any]] = []

        for idx, ((tool_name, args), result) in enumerate(zip(tool_names, results)):
            status = "error"
            output = {"status": "error", "data": {}}
            if isinstance(result, dict):
                output = result
                status = result.get("status", "error")
            elapsed_ms = int((time.monotonic() - start_times[idx]) * 1000)
            outputs[tool_name] = output
            store_tool_call(session_id, tool_name, args, status, elapsed_ms)
            timings.append(
                {
                    "tool": tool_name,
                    "status": status,
                    "execution_time_ms": elapsed_ms,
                    "arguments": args,
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
        if tool_name == "imdb":
            # Use TMDB as primary source (RapidAPI IMDb key expired)
            return services.tmdb_service.run(args.get("title", ""))
        if tool_name == "wikipedia":
            return services.wikipedia_service.run(args.get("title", ""))
        if tool_name == "watchmode":
            return services.watchmode_service.run(args.get("title", ""), args.get("region") or region)
        if tool_name == "similarity":
            return services.similarity_service.run(
                args.get("title", ""), imdb_id=args.get("imdb_id")
            )
        if tool_name == "archive":
            return services.archive_service.run(args.get("title", ""))
        if tool_name == "web_search":
            return services.web_search_service.run(args.get("query", ""))
        if tool_name == "imdb_trending_tamil":
            return services.discovery_engine_service.run_trending_tamil()
        if tool_name == "imdb_top_rated_english":
            return services.discovery_engine_service.run_top_rated_english()
        if tool_name == "imdb_upcoming":
            return services.discovery_engine_service.run_upcoming(args.get("country") or region)
        if tool_name == "imdb_person":
            # Use TMDB person lookup (RapidAPI IMDb key expired)
            return services.tmdb_service.get_person(
                name=args.get("name", "")
            )
        if tool_name == "rt_reviews":
            return services.rt_reviews_service.run(args.get("title", ""))
        # ── KB tools ─────────────────────────────────────────────────────
        if tool_name == "kb_entity":
            return kb_entity_lookup.run(args.get("title", ""))
        if tool_name == "kb_plot":
            return kb_plot_analysis.run(args.get("title", ""))
        if tool_name == "kb_critic":
            return kb_critic_summary.run(args.get("title", ""))
        if tool_name == "kb_similarity":
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
            return kb_movie_comparison.run(
                args.get("title_a", ""), args.get("title_b", "")
            )
        return None

    def _build_response(self, text: str, tool_outputs: Dict[str, Dict]) -> Dict[str, Any]:
        response = {
            "text_response": text,
            "poster_url": "",
            "streaming": [],
            "recommendations": [],
            "download_link": "",
            "sources": [],
        }
        # Poster from IMDb/TMDB API
        imdb = tool_outputs.get("imdb")
        if imdb and imdb.get("status") == "success":
            response["poster_url"] = imdb.get("data", {}).get("poster_url", "")
        # Poster from KB entity (TMDB poster_path)
        kb_entity = tool_outputs.get("kb_entity")
        if kb_entity and kb_entity.get("status") == "success" and not response["poster_url"]:
            poster_path = kb_entity.get("data", {}).get("poster_path", "")
            if poster_path:
                response["poster_url"] = f"https://image.tmdb.org/t/p/w500{poster_path}"
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
                {"title": r.get("title"), "year": r.get("year"), "imdb_id": r.get("imdb_id")}
                for r in recs
            ]
        # KB top rated movie list
        kb_top = tool_outputs.get("kb_top_rated")
        if kb_top and kb_top.get("status") == "success" and not response["recommendations"]:
            response["recommendations"] = kb_top.get("data", {}).get("movies", [])
        if not response["recommendations"]:
            for list_tool in ("imdb_trending_tamil", "imdb_top_rated_english", "imdb_upcoming"):
                output = tool_outputs.get(list_tool)
                if output and output.get("status") == "success":
                    response["recommendations"] = output.get("data", {}).get("movies", [])
                    break
        archive = tool_outputs.get("archive")
        if archive and archive.get("status") == "success":
            response["download_link"] = archive.get("data", {}).get("download_link", "")
        web_search = tool_outputs.get("web_search")
        if web_search and web_search.get("status") == "success":
            response["sources"] = web_search.get("data", {}).get("sources", [])
        return response

    def _profile_to_dict(self, profile) -> Dict[str, Any]:
        return {
            "region": getattr(profile, "region", None),
            "preferred_language": getattr(profile, "preferred_language", None),
            "subscribed_platforms": getattr(profile, "subscribed_platforms", None),
            "favorite_genres": getattr(profile, "favorite_genres", None),
            "favorite_movies": getattr(profile, "favorite_movies", None),
            "response_style": getattr(profile, "response_style", None),
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
            routing = trace.get("routing_matrix", {})
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
            lines.append(f'Query: "{msg}"')
            if resolved != msg:
                lines.append(f'Resolved: "{resolved}"')
            lines.append(f"")

            # Intent
            lines.append(f"Intent:")
            lines.append(f"- Primary: {primary} (confidence: {confidence})")
            if entities:
                ent_str = ", ".join(
                    f'{e.get("type","?")}: {e.get("value","?")}'
                    for e in entities if isinstance(e, dict)
                )
                lines.append(f"- Entities: [{ent_str}]")
            lines.append(f"")

            # Backend flow
            lines.append(f"Backend Flow:")
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

            # Cache
            lines.append(f"Cache:")
            lines.append(f"- Hits: {', '.join(cache_hits) if cache_hits else 'none'}")
            lines.append(f"- Misses: {', '.join(cache_misses) if cache_misses else 'none'}")
            lines.append(f"")

            # Tool timings
            lines.append(f"Tool Calls:")
            if timings:
                for t in timings:
                    lines.append(
                        f"- {t['tool']}: status={t['status']}, "
                        f"execution_time_ms={t['execution_time_ms']}, "
                        f"args={t.get('arguments', {})}"
                    )
            else:
                lines.append(f"- none")
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

            report_text = "\n".join(lines)
            with open(self._REPORT_PATH, "a", encoding="utf-8") as f:
                f.write(report_text + "\n")

            self.logger.info("LLM report appended to %s", self._REPORT_PATH)
        except Exception:
            self.logger.exception("Failed to write LLM report")

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
