"""
Entity Memory — Scored Entity Stack with Recency Decay
=======================================================
Replaces flat slot filling (last_movie / last_person) with a scored
entity stack that tracks recency, frequency, and conversational role.

Usage:
    memory = EntityMemory.from_json(saved_json)
    memory.add("Interstellar", "movie", "primary")
    memory.decay()
    primary = memory.primary()
    memory.to_json()
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Weights for the scoring formula:  score = w_r * recency + w_f * frequency_norm + w_role * role_weight
_W_RECENCY = 0.50
_W_FREQUENCY = 0.30
_W_ROLE = 0.20

_ROLE_WEIGHTS = {
    "primary": 1.0,
    "secondary": 0.6,
    "contextual": 0.3,
    "derived": 0.4,
}

_MAX_ENTITIES = 5
_PRUNE_THRESHOLD = 0.12
_DECAY_FACTOR = 0.7


class EntityMemory:
    """Scored entity stack with recency decay.

    Keeps up to ``_MAX_ENTITIES`` entities sorted by score descending.
    Each entity carries: value, type, role, recency (0-1), frequency, score.
    """

    def __init__(self, entities: list[dict[str, Any]] | None = None) -> None:
        self.entities: list[dict[str, Any]] = entities or []
        self._recalculate_scores()

    # ── Mutations ──────────────────────────────────────────────────────

    def add(self, value: str, entity_type: str, role: str = "primary") -> None:
        """Add or update an entity. Existing entities get frequency bump + recency reset."""
        if not value or not value.strip():
            return

        val_lower = value.strip().lower()

        # Update existing entity
        for e in self.entities:
            if e["value"].lower() == val_lower:
                e["frequency"] += 1
                e["recency"] = 1.0
                e["role"] = role
                e["type"] = entity_type  # In case type was refined
                self._recalculate_scores()
                return

        # New entity
        self.entities.append({
            "value": value.strip(),
            "type": entity_type,
            "role": role,
            "recency": 1.0,
            "frequency": 1,
            "score": 0.0,
        })
        self._recalculate_scores()
        self._prune()

    def decay(self) -> None:
        """Apply recency decay to all entities. Call once per turn."""
        for e in self.entities:
            e["recency"] *= _DECAY_FACTOR
        self._recalculate_scores()
        self._prune()

    # ── Queries ────────────────────────────────────────────────────────

    def primary(self) -> dict[str, Any] | None:
        """Return the highest-scoring entity, or None."""
        return self.entities[0] if self.entities else None

    def primary_movie(self) -> str | None:
        """Return the highest-scoring movie entity value, or None."""
        for e in self.entities:
            if e["type"] == "movie":
                return e["value"]
        return None

    def primary_person(self) -> str | None:
        """Return the highest-scoring person entity value, or None."""
        for e in self.entities:
            if e["type"] == "person":
                return e["value"]
        return None

    def get_by_role(self, role: str) -> list[dict[str, Any]]:
        """Return all entities with the given role."""
        return [e for e in self.entities if e["role"] == role]

    def all_values(self) -> list[str]:
        """Return all entity values in score order."""
        return [e["value"] for e in self.entities]

    # ── Serialization ─────────────────────────────────────────────────

    def to_json(self) -> str:
        return json.dumps(self.entities, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | list | None) -> EntityMemory:
        """Deserialize from a JSON string or list. Handles None/empty gracefully."""
        if not raw:
            return cls()
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return cls()
        elif isinstance(raw, list):
            data = raw
        else:
            return cls()
        return cls(entities=data)

    # ── Backward Compatibility ────────────────────────────────────────

    @classmethod
    def from_legacy_context(cls, last_movie: str | None, last_person: str | None) -> EntityMemory:
        """Bootstrap from old flat session context fields."""
        mem = cls()
        if last_movie:
            mem.add(last_movie, "movie", "primary")
        if last_person:
            mem.add(last_person, "person", "primary" if not last_movie else "secondary")
        return mem

    # ── Internals ─────────────────────────────────────────────────────

    def _recalculate_scores(self) -> None:
        max_freq = max((e["frequency"] for e in self.entities), default=1)
        for e in self.entities:
            freq_norm = e["frequency"] / max_freq if max_freq > 0 else 0
            role_w = _ROLE_WEIGHTS.get(e.get("role", "contextual"), 0.3)
            e["score"] = round(
                _W_RECENCY * e["recency"] + _W_FREQUENCY * freq_norm + _W_ROLE * role_w, 4
            )
        # Keep sorted by score descending
        self.entities.sort(key=lambda e: e["score"], reverse=True)

    def _prune(self) -> None:
        """Remove low-score entities and enforce max capacity."""
        self.entities = [e for e in self.entities if e["score"] >= _PRUNE_THRESHOLD]
        self.entities = self.entities[:_MAX_ENTITIES]

    def __repr__(self) -> str:
        items = ", ".join(f"{e['value']}({e['score']:.2f})" for e in self.entities)
        return f"EntityMemory([{items}])"
