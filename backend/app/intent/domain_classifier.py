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
from app.services.rag.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

# ── Domain descriptions ───────────────────────────────────────────────────────
# Each description is written as a semantic paragraph rather than a raw keyword list.
# Embedding models perform better when descriptions resemble natural language
# explanations of the domain rather than sparse keyword bags.

DOMAIN_DESCRIPTIONS: dict[str, str] = {

    "structured_data": (
        "Factual and database-style information about specific films and people including "
        "movie plot, story summary, synopsis, what happens in a film, cast, actors, "
        "director, release year, runtime, genre, rating, awards, nominations, box office, "
        "budget, production companies, streaming availability, where to watch, trailer, "
        "filmography of actors and directors, biographies of film personalities, "
        "IMDb style movie details, top rated movies, lowest rated movies. "
        "ALSO includes real-time and recent cinema information including trending movies, "
        "upcoming releases, current box office performance, breaking industry news, "
        "recent awards results, new trailers, casting announcements, and any query referencing "
        "current, latest, recent, new, upcoming, or this year."
    ),

    "film_criticism": (
        "Critical interpretation and evaluative analysis of specific films or filmmakers "
        "including auteur style, thematic analysis, symbolism, cultural impact, "
        "retrospective evaluation, critical essays, discussion of a director's body of "
        "work, comparisons between filmmakers, artistic significance, influence on cinema, "
        "and meaning-making within film culture. Use for questions asking why a film is "
        "considered great, what a director's style means, or how to interpret a film."
    ),

    "film_theory": (
        "Abstract academic frameworks and philosophy of cinema including semiotics, "
        "structuralism, apparatus theory, spectatorship, ideology, psychoanalytic theory, "
        "feminist film theory, realism versus formalism, montage theory, ontology of "
        "cinema, phenomenology, narrative theory, suture, and theoretical concepts used "
        "to explain how cinema as a medium creates meaning. Not about specific films — "
        "about cinema as a conceptual and philosophical object."
    ),

    "film_history": (
        "History of cinema as a cultural and industrial institution including the "
        "evolution of film movements, cinematic eras, and historical developments such as "
        "silent cinema, German expressionism, Soviet montage, Italian neorealism, "
        "French New Wave, British New Wave, film noir, New Hollywood, Iranian cinema, "
        "Japanese golden age, parallel cinema, and third cinema. Use only when the "
        "question is about a movement, era, or period in cinema history — NOT about "
        "the content, plot, or meaning of any individual film."
    ),

    "film_aesthetics": (
        "Cinematic form and visual style including mise en scène, cinematography, "
        "shot composition, lighting, color palette, depth of field, camera movement, "
        "tracking shots, editing rhythm, montage structure, sound design, film score, "
        "diegetic and non-diegetic sound, aspect ratio, and the technical and stylistic "
        "techniques used to construct meaning on screen. Use for questions about how "
        "a film looks, sounds, or is formally constructed."
    ),

    "film_analysis": (
        "Close reading and detailed interpretation of specific films or a specific "
        "filmmaker's body of work including scene-by-scene analysis, narrative structure "
        "of a particular film, character interpretation, thematic breakdown, symbolic "
        "reading, stylistic study of a director's technique across their filmography, "
        "and auteur studies grounded in specific works. Use when the question is anchored "
        "to a particular film or filmmaker — not cinema as a general concept. Examples: "
        "analyzing Bergman's use of silence, interpreting the ending of a specific film, "
        "comparing two films by the same director."
    ),

    "film_studies": (
        "Academic film studies as a discipline including introductory textbooks, survey "
        "courses, national cinema overviews, cultural and sociological studies of cinema "
        "as an institution, gender and identity in cinema, postcolonial film studies, "
        "Tamil cinema and Indian cinema as cultural systems, film and politics, "
        "representation studies, and multi-perspective edited volumes that map a field "
        "rather than argue a single interpretive position. Use when the question is "
        "about cinema as a social, cultural, or institutional phenomenon rather than "
        "about a specific film or theoretical concept."
    ),

    "film_production": (
        "Practical filmmaking craft and production process including directing technique, "
        "screenwriting, story structure, character arcs, dialogue writing, screenplay "
        "development, pre-production, shooting, cinematography practice, editing workflow, "
        "post-production, budgeting, financing, distribution, and documentary filmmaking. "
        "Use for how-to questions about making films."
    ),

    "film_scripts": (
        "Screenplays and film scripts including shooting scripts, screenplay format, "
        "dialogue scenes, script structure, full text scripts of films, script breakdowns, "
        "and screenplay analysis."
    ),



    "general": (
        "General conversation, greetings, and questions about FilmDB itself including "
        "hi, hello, what can you do, what are your capabilities, how can you help me, "
        "and what is this assistant."
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

