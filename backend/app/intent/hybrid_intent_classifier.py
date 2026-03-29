"""
C.3 — HybridIntentClassifier
==============================
3-tier hybrid intent classification pipeline.

Tier 1  – DomainClassifier: embedding cosine similarity → domain + routing mode
Tier 2  – Sub-intent agent (narrow LLM prompt per domain) → primary_intent + confidence
Tier 3  – Entity extraction: already handled by EntityResolver downstream

Multi-domain mode (0.42 ≤ tier1_score < 0.68):
  – Both top-2 domains run their Tier 2 agents in parallel
  – Results are merged: primary intent from highest-confidence domain,
  – Tool selector receives BOTH domains to merge tool lists

Usage:
    clf = HybridIntentClassifier(llm, secondary_llm=None)
    result = clf.classify(message)
    # result keys: primary_intent, secondary_intents, entities, confidence, domain
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.intent.domain_classifier import DomainClassifier
from app.intent.sub_intent_agents import DOMAIN_AGENTS, GeneralAgent

logger = logging.getLogger(__name__)

# Domains that map to tool_selector intents directly
# (no sub-intent agent LLM call needed)
_FAST_DOMAINS = {"general"}

# When merging multi-domain results, these intents from the secondary domain
# are always added as secondary_intents rather than overriding primary
_SECONDARY_MERGE_INTENTS = {
    "STREAMING_AVAILABILITY", "OSCAR_LOOKUP", "GENERAL_AWARD_LOOKUP",
    "DOWNLOAD", "TRENDING", "TOP_RATED",
}


class HybridIntentClassifier:
    """
    3-tier hybrid intent classification pipeline.
    Returns a dict with intent, domain, and confidence data.
    """

    def __init__(self, primary_llm, secondary_llm=None) -> None:
        self.primary_llm = primary_llm
        self.secondary_llm = secondary_llm
        self.logger = logging.getLogger(__name__)
        # DomainClassifier is a singleton — first call loads the model
        self._domain_clf = DomainClassifier.get_instance()

    # ── Public API ────────────────────────────────────────────────────────────

    def classify(self, message: str) -> dict[str, Any]:
        """
        Main entry point. Returns intent dict.
        """

        # ── Tier 1: Domain classification (Embedding Centroids) ───────────────
        # Identifies the broad "Topic Area" (e.g., film_theory, film_history)
        # using semantic cosine similarity.
        domain_result = self._domain_clf.classify(message)
        self.logger.info(
            "HybridIntentClassifier Tier-1: domain=%s score=%.3f mode=%s",
            domain_result.domain, domain_result.score, domain_result.mode,
        )

        # ── Tier 2: Sub-intent classification (Specialized LLM Agents) ────────
        # Hand-off: The identified Domain from Tier 1 is used to select a 
        # specialized LLM sub-agent with a domain-specific system prompt.
        if domain_result.mode == "single":
            result = self._run_agent(domain_result.domain, message)
            result["domain"] = domain_result.domain
            result["domain_score"] = round(domain_result.score, 3)

        elif domain_result.mode == "multi":
            # Both top-2 domains run their agents and results are merged
            d1_name = domain_result.top2[0][0]
            d1_score = domain_result.top2[0][1]
            d2_name = domain_result.top2[1][0]
            d2_score = domain_result.top2[1][1]
            
            r1 = self._run_agent(d1_name, message)
            r2 = self._run_agent(d2_name, message)

            # Merge: higher weighted-confidence intent is primary.
            # We multiply LLM confidence by the Tier-1 semantic domain score
            # to prevent an academic sub-agent from hallucinating 99% confidence 
            # and hijacking an ambiguous query that Top-1 correctly identified.
            c1 = r1.get("confidence", 70) * d1_score
            c2 = r2.get("confidence", 70) * d2_score

            if c2 > c1:
                r1, r2 = r2, r1
                d1_name, d2_name = d2_name, d1_name

            secondary_intents = list(r1.get("secondary_intents", []))
            r2_primary = r2.get("primary_intent", "")
            if r2_primary and r2_primary not in secondary_intents:
                secondary_intents.append(r2_primary)

            result = {
                "primary_intent": r1.get("primary_intent", "ENTITY_LOOKUP"),
                "secondary_intents": secondary_intents,
                "entities": _merge_entities(
                    r1.get("entities", []), r2.get("entities", [])
                ),
                "confidence": r1.get("confidence", 70),
                "domain": d1_name,
                "secondary_domain": d2_name,
                "domain_score": round(domain_result.score, 3),
            }

        else:  # "default" — low confidence, safe fallback to structured_data
            result = self._run_agent("structured_data", message)
            result["domain"] = "structured_data"
            result["domain_score"] = round(domain_result.score, 3)

        result["classifier"] = "hybrid"
        self.logger.info(
            "HybridIntentClassifier result: intent=%s domain=%s conf=%s",
            result.get("primary_intent"), result.get("domain"), result.get("confidence"),
        )
        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _run_agent(self, domain: str, message: str) -> dict[str, Any]:
        """Run the sub-intent agent for a given domain."""
        agent = DOMAIN_AGENTS.get(domain, DOMAIN_AGENTS["structured_data"])
        if isinstance(agent, GeneralAgent):
            return agent.classify(message)
        try:
            return agent.classify(message, self.primary_llm)  # type: ignore[arg-type]
        except Exception as exc:
            self.logger.warning(
                "Sub-intent agent for domain '%s' failed: %s — using fallback LLM",
                domain, exc,
            )
            if self.secondary_llm:
                try:
                    return agent.classify(message, self.secondary_llm)  # type: ignore[arg-type]
                except Exception:
                    pass
            return {
                "primary_intent": "ENTITY_LOOKUP" if domain == "structured_data" else "CONCEPTUAL_EXPLANATION",
                "secondary_intents": [],
                "entities": [],
                "confidence": 65,
            }


def _merge_entities(a: list, b: list) -> list:
    """Merge two entity lists deduplicating by (type, value)."""
    seen: set[tuple] = set()
    merged: list[dict] = []
    for ent in a + b:
        if not isinstance(ent, dict):
            continue
        key = (ent.get("type", ""), str(ent.get("value", "")).lower())
        if key not in seen:
            seen.add(key)
            merged.append(ent)
    return merged

