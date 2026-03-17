"""
C.1 — DomainClassifier
======================
Tier 1 of the hybrid intent pipeline. Uses cosine similarity against 7 domain
description embeddings to route queries to the correct domain before any LLM call.

Model: BAAI/bge-base-en-v1.5 (shared via EmbeddingService singleton)
Cost: ~1–3 ms per query, zero tokens.
"""

from __future__ import annotations

import logging
import numpy as np
from typing import NamedTuple
from app.services.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

# ── Domain descriptions ───────────────────────────────────────────────────────
# Each description is written as a semantic paragraph rather than a raw keyword list.
# Embedding models perform better when descriptions resemble natural language
# explanations of the domain rather than sparse keyword bags.

DOMAIN_DESCRIPTIONS: dict[str, str] = {

    "structured_data": (
        "Film database information and movie metadata including film title, cast, actors, "
        "director, release year, runtime, genre, rating, awards, nominations, box office, "
        "budget, production companies, streaming availability, where to watch, trailer, "
        "filmography of actors and directors, biographies of film personalities, "
        "IMDb style movie details and factual information about films,top rated movies, top, "
        "low rated movies, watch, download, watch online"
    ),

    "film_criticism": (
        "Film criticism and critical interpretation of movies and filmmakers including "
        "analysis of directors, auteur style, thematic interpretation, symbolism, cultural "
        "impact of films, retrospective evaluations, critical essays about cinema, "
        "discussion of a director's body of work, comparisons between filmmakers, "
        "interpretations of meaning, influence, artistic significance, and evaluation "
        "of films within cinema culture."
    ),

    "film_theory": (
        "Academic film theory and philosophy of cinema including concepts such as "
        "semiotics, structuralism, apparatus theory, spectatorship theory, ideology in film, "
        "psychoanalytic film theory, feminist film theory, realism versus formalism, "
        "montage theory, ontology of cinema, phenomenology of film experience, narrative "
        "theory, suture, cinematic language, and theoretical frameworks used to analyze "
        "how cinema creates meaning."
    ),

    "film_history": (
        "History of cinema including the evolution of film movements, cinematic eras and "
        "historical developments in world cinema such as silent cinema, classical Hollywood, "
        "German expressionism, Soviet montage, Italian neorealism, French new wave, "
        "British new wave, film noir, new Hollywood, Iranian cinema, Japanese golden age, "
        "parallel cinema, third cinema, and the cultural or political context that shaped "
        "the development of cinema across decades. history of cinema evolution, film movements like french new wave and italian neorealism, development of world cinema across decades"
    ),

    "film_aesthetics": (
        "Film aesthetics and cinematic form including visual style, mise en scene, "
        "cinematography, shot composition, lighting design, color palette, depth of field, "
        "camera movement, tracking shots, editing rhythm, montage structure, sound design, "
        "film score, diegetic and non diegetic sound, aspect ratio, visual storytelling, "
        "film language and stylistic techniques used to construct cinematic meaning."
    ),

    "film_production": (
        "Filmmaking craft and production processes including directing, screenwriting, "
        "story structure, character arcs, dialogue writing, screenplay development, "
        "preproduction planning, shooting films, production workflow, cinematography "
        "practice, editing workflow, post production, budgeting, financing, film "
        "distribution, documentary filmmaking, and practical techniques used in "
        "creating movies."
    ),

    "film_scripts": (
        "Screenplays and film scripts including shooting scripts, screenplay format, "
        "dialogue scenes, script structure, movie screenplays, downloadable scripts, "
        "screenplay analysis, script breakdowns, and full text scripts of films."
    ),

    "general": (
        "General conversation, greetings, bot interaction, and questions about how to use FilmDB. "
        "This includes greetings like hi, hello, howdy, but importantly also questions like "
        "what can you do, what are your capabilities, how can you help me, what is this assistant "
        "for. Strictly for non-movie and non-knowledge inquiries."
    ),
}

# Confidence thresholds
HIGH_CONFIDENCE = 0.68   # → single domain, proceed to Tier 2
LOW_CONFIDENCE  = 0.42   # → below this, default to structured_data (safe)
# Between LOW and HIGH → top-2 multi-domain mode


class DomainResult(NamedTuple):
    domain: str
    score: float
    top2: list[tuple[str, float]]   # always the top-2 (domain, score) pairs
    mode: str                        # "single" | "multi" | "default"


class DomainClassifier:
    """
    Singleton — call DomainClassifier.get_instance() to reuse the loaded model.
    """
    _instance: "DomainClassifier | None" = None

    def __init__(self) -> None:
        self._emb     = EmbeddingService.get_instance()
        self._domains = list(DOMAIN_DESCRIPTIONS.keys())
        logger.info("DomainClassifier: encoding centroids with %s …", self._emb.MODEL_NAME)
        self._centroids = self._emb.encode_passages(
            list(DOMAIN_DESCRIPTIONS.values())
        )   # shape (7, dim)
        logger.info("DomainClassifier: ready (%d domains, dim=%d)",
                    len(self._domains), self._centroids.shape[1])

    @classmethod
    def get_instance(cls) -> "DomainClassifier":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # Fast-path overrides removed — all routing now goes through
    # embedding cosine similarity to support multi-domain queries.

    def classify(self, message: str) -> DomainResult:
        # Embed query using EmbeddingService (BGE asymmetric prefix)
        q_vec = self._emb.encode_query(message)   # shape (dim,)
        scores: np.ndarray = self._centroids @ q_vec   # cosine similarity per domain

        ranked = sorted(
            zip(self._domains, scores.tolist()),
            key=lambda x: x[1], reverse=True,
        )
        top1_domain, top1_score = ranked[0]
        top2_domain, top2_score = ranked[1]
        top2_list = ranked[:2]

        if top1_score >= HIGH_CONFIDENCE:
            return DomainResult(top1_domain, top1_score, top2_list, "single")
        elif top1_score >= LOW_CONFIDENCE:
            return DomainResult(top1_domain, top1_score, top2_list, "multi")
        else:
            return DomainResult("structured_data", top1_score, top2_list, "default")
