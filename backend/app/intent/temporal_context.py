"""
TemporalContextBuilder
======================
Lightweight helper that gives the UnifiedIntentToolAgent (and the response
synthesis prompt) awareness of:
  - The current real-world date
  - The LLM's training knowledge cutoff
  - The temporal nature of the user's query

No LLM calls, no I/O — fast, deterministic.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


class TemporalContextBuilder:
    """
    Stateless helper.  All methods are classmethods — no instantiation needed.
    """

    # ── Knowledge cutoff ──────────────────────────────────────────────────────
    KNOWLEDGE_CUTOFF_LABEL = "March 2025"
    KNOWLEDGE_CUTOFF_YEAR  = 2025
    KNOWLEDGE_CUTOFF_MONTH = 3   # March

    # ── Year pattern ──────────────────────────────────────────────────────────
    _YEAR_RE = re.compile(r"\b(19[0-9]{2}|20[0-9]{2})\b")

    # ── Recency keywords ──────────────────────────────────────────────────────
    _CURRENT_KEYWORDS = frozenset([
        "latest", "recent", "current", "now", "today", "this year",
        "this month", "upcoming", "new release", "just released",
        "breaking", "trending", "2025", "2026", "2027",
    ])
    _HISTORICAL_CUTOFF_YEAR = 2020   # before this → always historical

    # ─────────────────────────────────────────────────────────────────────────
    #  Public API
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def get_current_date_context(cls) -> str:
        """
        Returns a temporal context string to inject into LLM prompts.
        Example:
            TEMPORAL CONTEXT:
            Today        : Saturday, March 21, 2026
            Knowledge cutoff: March 2025
            ...
        """
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%A, %B %d, %Y")
        months_past_cutoff = (
            (now.year - cls.KNOWLEDGE_CUTOFF_YEAR) * 12
            + (now.month - cls.KNOWLEDGE_CUTOFF_MONTH)
        )

        return (
            f"TEMPORAL CONTEXT:\n"
            f"  Today             : {date_str}\n"
            f"  Knowledge cutoff  : {cls.KNOWLEDGE_CUTOFF_LABEL} "
            f"({months_past_cutoff} months ago)\n"
            f"\n"
            f"TEMPORAL RULES:\n"
            f"  - For events/films/people BEFORE {cls.KNOWLEDGE_CUTOFF_LABEL}: "
            f"your training knowledge is reliable. Verify with tools if high precision needed.\n"
            f"  - For events AFTER {cls.KNOWLEDGE_CUTOFF_LABEL}: "
            f"DO NOT guess. Use cinema_search or other live tools as the ONLY source.\n"
            f"  - If no live tool data is available for a post-cutoff query, "
            f"clearly state the limitation rather than hallucinating.\n"
        )

    @classmethod
    def detect_temporal_type(cls, query: str) -> dict[str, Any]:
        """
        Analyse a query's temporal nature without an LLM call.

        Returns:
            {
                "type":                  "timeless" | "historical" | "recent" | "current",
                "requires_live_data":    bool,
                "confidence_in_internal": float (0.0–1.0),
                "detected_years":        list[int],
                "note":                  str
            }
        """
        q_lower = query.lower()
        detected_years = [int(y) for y in cls._YEAR_RE.findall(query)]

        # ── "current" signals ─────────────────────────────────────────────
        has_current_kw = any(kw in q_lower for kw in cls._CURRENT_KEYWORDS)
        post_cutoff_years = [
            y for y in detected_years
            if y > cls.KNOWLEDGE_CUTOFF_YEAR
            or (y == cls.KNOWLEDGE_CUTOFF_YEAR and datetime.now(timezone.utc).month > cls.KNOWLEDGE_CUTOFF_MONTH)
        ]

        if has_current_kw or post_cutoff_years:
            return {
                "type":                   "current",
                "requires_live_data":     True,
                "confidence_in_internal": 0.0,
                "detected_years":         detected_years,
                "note": (
                    f"Post-cutoff year {post_cutoff_years} detected" if post_cutoff_years
                    else "Recency keyword detected"
                ),
            }

        # ── "historical" signals ──────────────────────────────────────────
        historical_years = [y for y in detected_years if y < cls._HISTORICAL_CUTOFF_YEAR]
        if historical_years:
            return {
                "type":                   "historical",
                "requires_live_data":     False,
                "confidence_in_internal": 0.90,
                "detected_years":         detected_years,
                "note": f"Historical year {historical_years} — training data is reliable",
            }

        # ── years in the "recent but pre-cutoff" range ────────────────────
        recent_years = [
            y for y in detected_years
            if cls._HISTORICAL_CUTOFF_YEAR <= y <= cls.KNOWLEDGE_CUTOFF_YEAR
        ]
        if recent_years:
            return {
                "type":                   "recent",
                "requires_live_data":     False,
                "confidence_in_internal": 0.70,
                "detected_years":         detected_years,
                "note": f"Recent pre-cutoff year {recent_years} — mostly reliable but verify with tools",
            }

        # ── no year mention, no recency signals → timeless ───────────────
        return {
            "type":                   "timeless",
            "requires_live_data":     False,
            "confidence_in_internal": 0.95,
            "detected_years":         [],
            "note": "No temporal signals — answer from training knowledge",
        }
