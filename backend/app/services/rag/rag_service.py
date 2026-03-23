"""
RAGService — Unified Multi-Domain Retrieval Pipeline
=====================================================
Two-stage retrieval:
  Stage 1 (Recall):   BAAI/bge-base-en-v1.5  (Bi-Encoder, fast, ~28K+ vectors)
  Stage 2 (Precision): BAAI/bge-reranker-base (Cross-Encoder, accurate, on 15–20 candidates)

Collections (ChromaDB, all cosine):
  analysis          ← film analysis essays (Senses of Cinema, BFI, etc.)
  plots             ← Wikipedia plot chunks (has imdb_id metadata)
  film_theory       ← books: abstract theory, philosophy of cinema
  film_criticism    ← books: journalistic criticism, filmmaker writings
  film_history      ← books: biographies, movement histories
  film_aesthetics   ← books: cinematography, visual style craft
  film_production   ← books: directing, screenwriting, production workflow
  scripts           ← screenplay/script PDFs
  film_analysis     ← books: close readings, auteur/director studies  [NEW]
  film_studies      ← books: survey texts, national cinema, intro textbooks [NEW]

Public API:
    rag = RAGService.get_instance()
    # Legacy (still works, internally unified):
    rag.query_analysis(query)
    rag.query_plots(query, imdb_id=...)
    rag.query_books(query, domain="film_criticism")
    # New unified entrypoint:
    rag.query_unified(query, query_type, primary_domain, secondary_domain, imdb_id, person_name)
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CHROMA_DIR = Path(__file__).resolve().parents[4] / "rag" / "storage" / "chromadb_store"
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

ALL_DOMAINS = [
    "articles",
    "film_theory",
    "film_criticism",
    "film_history",
    "film_aesthetics",
    "film_production",
    "scripts",
    "plots",
    "film_analysis",   # close readings, auteur/director studies
    "film_studies",    # survey texts, national cinema, intro textbooks
]

# Map intent-domain names → ChromaDB collection names
INTENT_DOMAIN_MAP: dict[str, str] = {
    "structured_data":  "articles",
    "film_theory":      "film_theory",
    "film_criticism":   "film_criticism",
    "film_history":     "film_history",
    "film_aesthetics":  "film_aesthetics",
    "film_production":  "film_production",
    "film_analysis":    "film_analysis",   # NEW — direct pass-through
    "film_studies":     "film_studies",    # NEW — direct pass-through
    "general":          "articles",
    "plots":            "plots",
}

# Collections that store imdb_id in metadata (allows hard ChromaDB WHERE filtering)
IMDB_FILTERABLE_COLLECTIONS = {"plots", "articles"}

# Which metadata keys each collection actually supports for hard filtering
# (determined by real DB audit — only keys that are populated)
COLLECTION_FILTERABLE_KEYS: dict[str, set[str]] = {
    "plots":    {"director", "title", "cast", "genre", "year", "imdb_id"},
    "articles": {"entity_name", "knowledge_type", "title"},
    "scripts":  {"director", "title", "year", "genre"},  # enriched via enrich_scripts_metadata.py
    # All book collections: NO entity-level filters — use query expansion instead
}

# ── Domain routing keyword map ─────────────────────────────────────────────────
# High-quality, non-overlapping keyword sets per primary domain.
# Used to resolve a query to the best target collections.
DOMAIN_KEYWORDS: dict[str, set[str]] = {
    "film_history": {
        "history", "movement", "era", "period", "decade", "century", "timeline",
        "1920s", "1930s", "1940s", "1950s", "1960s", "1970s", "1980s", "1990s",
        "new wave", "expressionism", "neorealism", "pre-code", "golden age",
        "soviet", "french", "italian", "german", "classical hollywood", "evolution",
        "origin", "birth of", "rise of", "influence of", "historical", "archival",
    },
    "film_theory": {
        "theory", "theoretical", "semiotics", "apparatus", "gaze", "ideology",
        "psychoanalysis", "structuralism", "auteur", "formalism", "realism theory",
        "phenomenology", "ontology", "representation", "suture", "diegesis",
        "feminist theory", "postmodernism", "postcolonial", "spectatorship",
        "bazin", "eisenstein", "metz", "mulvey", "deleuze", "lacan",
        "medium specificity", "indexicality", "frame theory",
    },
    "film_criticism": {
        "review", "critique", "criticism", "interpretation", "reading",
        "thematic analysis", "meaning", "subtext", "symbolism", "allegory",
        "analysis of", "significance", "what does it mean", "deeper meaning",
        "critical perspective", "canonical status", "cultural impact",
        "masterpiece", "auteur study", "revisionist reading",
    },
    "film_aesthetics": {
        "visual", "aesthetics", "style", "cinematography", "composition",
        "lighting", "framing", "shot", "mise-en-scène", "colour", "color palette",
        "lens", "depth of field", "symmetry", "long take", "handheld",
        "tracking shot", "dolly", "steadicam", "camerawork", "visual motif",
        "aspect ratio", "widescreen", "close-up", "montage aesthetics",
        "production design", "costume", "set design",
    },
    "film_production": {
        "production", "directing", "directing technique", "workflow",
        "pre-production", "post-production", "editing", "sound design",
        "foley", "vfx", "special effects", "practical effects", "storyboard",
        "screenplay writing", "script development", "casting",
        "budget", "financing", "distribution", "behind the scenes",
        "director style", "cinematographer", "how was it made",
    },
    "scripts": {
        "dialogue", "script", "screenplay", "scene", "act", "character arc",
        "monologue", "line", "script analysis", "what does the character say",
        "screenplay structure", "three-act", "beat sheet", "character motivation",
    },
    "articles": {
        "analysis", "essay", "scholarly", "academic", "film essay",
        "review essay", "senses of cinema", "criterion", "bfi", "sight and sound",
        "written about", "critic wrote", "piece on", "article about",
    },
    "plots": {
        "plot", "story", "storyline", "narrative", "what happens",
        "synopsis", "summary", "beginning", "ending", "climax", "twist",
        "what is the movie about", "does he die", "does she",
    },
    # New domains from reclassification
    "film_analysis": {
        "auteur", "auteur study", "director study", "close reading", "close analysis",
        "bergman's", "tarkovsky's", "kubrick's", "lynch's", "haneke's", "tarr's",
        "films of", "cinema of", "interpret", "explain this film", "what does it mean",
        "analyze this film", "breakdown", "scene analysis", "character study",
        "thematic reading", "stylistic study", "director's technique",
    },
    "film_studies": {
        "national cinema", "world cinema", "indian cinema", "tamil cinema",
        "introduction to", "intro to film", "study of cinema", "cinema as institution",
        "gender in cinema", "representation in film", "postcolonial cinema",
        "film as culture", "sociology of cinema", "politics and film",
        "survey of", "overview of cinema", "film education",
    },
}


def _resolve_domains(
    query: str,
    query_type: str,
    primary_domain: str | None,
    secondary_domain: str | None,
) -> list[str]:
    """
    Determine which ChromaDB collections to query based on query_type,
    primary/secondary domain hints, and keyword matching.
    Returns an ordered list of collection names.
    """
    targets: list[str] = []
    query_lower = query.lower()

    # ------------------------------------------------------------------
    # Step 1: Use explicit domain hints from tool_selector
    # ------------------------------------------------------------------
    for d in [primary_domain, secondary_domain]:
        if not d:
            continue
        mapped = INTENT_DOMAIN_MAP.get(d, d)
        if mapped in ALL_DOMAINS and mapped not in targets:
            targets.append(mapped)

    # ------------------------------------------------------------------
    # Step 2: Augment with keyword-based domain detection on the query
    # ------------------------------------------------------------------
    keyword_hits: dict[str, int] = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in query_lower)
        if score > 0:
            keyword_hits[domain] = score

    # Add keyword-discovered domains by score (highest first)
    for domain in sorted(keyword_hits, key=keyword_hits.get, reverse=True):
        if domain not in targets:
            targets.append(domain)

    # ------------------------------------------------------------------
    # Step 3: Apply query_type defaults if still sparse
    # ------------------------------------------------------------------
    if query_type == "analytical":
        # Film analysis: auteur/director studies most relevant, then aesthetics + plots
        for col in ["film_analysis", "plots", "film_aesthetics", "film_criticism", "analysis"]:
            if col not in targets:
                targets.append(col)
    elif query_type == "conceptual":
        # Theory/history/cultural studies: theory books + film_studies for surveys
        for col in ["film_theory", "film_history", "film_studies", "film_aesthetics", "analysis", "plots"]:
            if col not in targets:
                targets.append(col)
    else:
        # Default: analysis essays + plots as safety net
        for col in ["articles", "plots"]:
            if col not in targets:
                targets.append(col)

    # Always keep targets to a sensible maximum (avoid querying all 10 for simple queries)
    return targets[:6]


def _build_quotas(targets: list[str], query_type: str, total: int = 18) -> dict[str, int]:
    """
    Assign recall quotas per collection, biased by query_type.
    Ensures no collection gets 0, so cross-domain references always surface.
    """
    n = len(targets)
    if n == 0:
        return {}

    quotas: dict[str, int] = {}

    if query_type == "analytical":
        # Film analysis (auteur/director studies) gets highest priority
        for col in targets:
            if col == "film_analysis":
                quotas[col] = 6   # auteur studies are most relevant for analytical
            elif col == "plots":
                quotas[col] = 5   # narrative grounding
            elif col in ("film_aesthetics", "film_criticism", "articles"):
                quotas[col] = 4
            else:
                quotas[col] = 2

    elif query_type == "conceptual":
        # Theory/history/cultural queries
        for col in targets:
            if col in ("film_theory", "film_history"):
                quotas[col] = 5
            elif col in ("film_aesthetics", "film_studies"):
                quotas[col] = 4   # film_studies good for cultural/national cinema
            elif col in ("film_criticism", "film_production", "articles"):
                quotas[col] = 3
            elif col == "film_analysis":
                quotas[col] = 3   # auteur studies can add depth to conceptual
            elif col == "plots":
                quotas[col] = 2   # never zero — cross-domain references possible
            else:
                quotas[col] = 2
    else:
        # Default: balanced
        per_col = max(2, total // n)
        for col in targets:
            quotas[col] = per_col

    return quotas


class RAGService:
    """
    Singleton. Call RAGService.get_instance().
    ChromaDB collections are loaded lazily on first access per domain.
    """
    _instance: "RAGService | None" = None

    def __init__(self) -> None:
        import chromadb
        from app.services.rag.embedding_service import EmbeddingService

        logger.info("RAGService: initialising ChromaDB client at %s", CHROMA_DIR)
        self._client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self._emb    = EmbeddingService.get_instance()
        self._collections: dict[str, Any] = {}
        self._reranker = None   # lazy-loaded on first call to query_unified

    @classmethod
    def get_instance(cls) -> "RAGService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Re-ranker lazy loader ──────────────────────────────────────────────────

    def _get_reranker(self):
        """Lazy-load BAAI/bge-reranker-base on first use."""
        if self._reranker is None:
            try:
                from sentence_transformers import CrossEncoder
                logger.info("RAGService: loading BAAI/bge-reranker-base cross-encoder …")
                self._reranker = CrossEncoder("BAAI/bge-reranker-base")
                logger.info("RAGService: cross-encoder ready.")
            except Exception as exc:
                logger.error("RAGService: failed to load cross-encoder — %s", exc)
        return self._reranker

    # ── Collection lazy loader ─────────────────────────────────────────────────

    def _get_collection(self, name: str):
        """Return the ChromaDB collection for `name`, or None if it doesn't exist yet."""
        if name not in self._collections:
            try:
                col = self._client.get_collection(name=name)
                if col.count() == 0:
                    raise ValueError("empty")
                self._collections[name] = col
                logger.info("RAGService: loaded collection '%s' (%d docs)", name, col.count())
            except Exception as exc:
                logger.warning(
                    "RAGService: collection '%s' unavailable (%s). "
                    "Run rag/ingest/embed_*.py first.",
                    name, exc,
                )
                return None
        return self._collections[name]

    # ── Windowed parent retrieval ─────────────────────────────────────────────

    def _expand_window(self, item: dict) -> dict:
        """
        Phase 2.1 — Windowed Parent Retrieval.
        
        Applies 3-Tier Expansion Logic based on collection data scale:
        1. 'plots': Full expansion (fetches all chunks for the movie, avg 1.3 chunks)
        2. 'analysis': Capped expansion (fetches [-2, +2] chunks, ~1,250 words total)
        3. All others (books/scripts): Surgical expansion (fetches [-1, +1] chunks)
        """
        parent_id = item.get("parent_id") or item.get("meta_parent_id", "")
        domain = item.get("domain", "")
        
        # If no parent_id, we can't do any windowing
        if not parent_id:
            return item
            
        col = self._get_collection(domain)
        if col is None:
            return item

        try:
            if domain == "plots":
                # Retrieve all chunks for the plot and stitch them back together
                where = {"parent_id": {"$eq": parent_id}}
                result = col.get(where=where, include=["documents", "metadatas"])
                neighbours = sorted(
                    zip(result["documents"], result["metadatas"]),
                    key=lambda x: int(x[1].get("chunk_position", 0))
                )
                expanded = " ".join([doc for doc, meta in neighbours])
                item = dict(item)
                item["passage"] = expanded
                item["windowed"] = True
                logger.debug("_expand_window: fully expanded plot '%s' to %d chars",
                             parent_id, len(expanded))
                return item

            # For everything else, we need chunk_position
            pos = item.get("chunk_position")
            if pos is None:
                return item
                
            pos = int(pos)
            
            if domain == "articles":
                neighbour_positions = [p for p in (pos - 2, pos - 1, pos + 1, pos + 2) if p >= 0]
            else:
                neighbour_positions = [p for p in (pos - 1, pos + 1) if p >= 0]
                
            if not neighbour_positions:
                return item

            where = {
                "$and": [
                    {"parent_id": {"$eq": parent_id}},
                    {"chunk_position": {"$in": neighbour_positions}},
                ]
            }
            result = col.get(where=where, include=["documents", "metadatas"])
            neighbours = sorted(
                zip(result["documents"], result["metadatas"]),
                key=lambda x: int(x[1].get("chunk_position", 0))
            )

            before_texts = [doc for doc, meta in neighbours if int(meta.get("chunk_position", pos)) < pos]
            after_texts  = [doc for doc, meta in neighbours if int(meta.get("chunk_position", pos)) > pos]

            original = item["passage"]
            expanded = " ".join(before_texts + [original] + after_texts)
            item = dict(item)  # shallow copy so we don't mutate the shared dict
            item["passage"] = expanded
            item["windowed"] = True  # telemetry flag
            logger.debug("_expand_window: expanded '%s'@%d from %d→%d chars",
                         parent_id, pos, len(original), len(expanded))
            return item
            
        except Exception as exc:
            logger.warning("_expand_window: neighbour fetch failed for '%s': %s", parent_id, exc)
            return item

    # ── WHERE clause builder (per-collection metadata filtering) ──────────────

    def _build_where_clause(
        self,
        collection_name: str,
        imdb_filter: dict | None,
        metadata_filters: dict,
    ) -> dict | None:
        """
        Build a ChromaDB WHERE clause from metadata_filters,
        only applying keys that this collection actually supports.
        """
        conditions: list[dict] = []

        # Legacy imdb_id filter (backward compatible)
        if imdb_filter and collection_name in IMDB_FILTERABLE_COLLECTIONS:
            conditions.append({"imdb_id": {"$eq": imdb_filter["imdb_id"]}})

        # New metadata filters from router — only apply supported keys
        if metadata_filters:
            allowed = COLLECTION_FILTERABLE_KEYS.get(collection_name, set())
            for key, value in metadata_filters.items():
                if key in allowed and value:
                    conditions.append({key: {"$eq": value}})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    # ── Private recall helper ─────────────────────────────────────────────────

    def _recall_from_collection(
        self,
        collection_name: str,
        q_vec: list[float],
        n_results: int,
        metadata_filter: dict | None,
        query_text: str = "",
    ) -> list[tuple[dict, float]]:
        """Query one ChromaDB collection and return (item_dict, score) pairs."""
        col = self._get_collection(collection_name)
        if col is None:
            return []

        n_available = col.count()
        if n_available == 0:
            return []

        fetch = min(n_results, n_available)
        try:
            # Only apply metadata_filter if this collection supports it
            where = metadata_filter if collection_name in IMDB_FILTERABLE_COLLECTIONS else None
            results = col.query(
                query_embeddings=[q_vec],
                n_results=fetch,
                where=where,
                include=["documents", "metadatas", "distances"] # Note: ids are returned by default regardless of include
            )
        except Exception as exc:
            logger.warning("ChromaDB query failed for '%s': %s", collection_name, exc)
            return []

        dense_ids = results["ids"][0]
        dense_docs = results["documents"][0]
        dense_metas = results["metadatas"][0]

        # ── HYBRID SPARTA: Fetch BM25 ──
        sparse_ids = []
        if query_text:
            try:
                from app.services.rag.bm25_service import BM25Service
                sparse_hits = BM25Service.get_instance().query_collection(collection_name, query_text, top_k=n_results)
                sparse_ids = [hit[0] for hit in sparse_hits]
            except Exception as e:
                logger.warning("BM25 fetch failed: %s", e)

        # RRF scoring
        k = 60
        rrf_scores = {}
        for rank, doc_id in enumerate(dense_ids):
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
        for rank, doc_id in enumerate(sparse_ids):
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)

        # Map existing metadata
        doc_map = {did: (doc, meta) for did, doc, meta in zip(dense_ids, dense_docs, dense_metas)}

        # Fetch missing metadata for BM25-exclusive hits
        missing_ids = [did for did in rrf_scores.keys() if did not in dense_ids]
        if missing_ids:
            try:
                missing_data = col.get(ids=missing_ids, include=["documents", "metadatas"])
                for did, doc, meta in zip(missing_data["ids"], missing_data["documents"], missing_data["metadatas"]):
                    doc_map[did] = (doc, meta)
            except Exception as exc:
                logger.warning("ChromaDB get() missing_ids failed for '%s': %s", collection_name, exc)

        # Sort by RRF score descending
        sorted_rrf = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

        items = []
        for doc_id, rrf_score in sorted_rrf[:n_results]:
            if doc_id not in doc_map:
                continue
            doc, meta = doc_map[doc_id]
            
            # Pack item using identical legacy structure
            items.append((
                {
                    "doc_id":      doc_id,
                    "passage":     doc,
                    "domain":      collection_name,
                    "source":      meta.get("source", collection_name),
                    "entity_name": meta.get("entity_name", ""),
                    "imdb_id":     meta.get("imdb_id", ""),
                    "title":       meta.get("title", ""),
                    "director":    meta.get("director", ""),
                    "cast":        meta.get("cast", ""),
                    "year":        meta.get("year", ""),
                    "genre":       meta.get("genre", ""),
                    "author":      meta.get("author", ""),
                    "filename":    meta.get("filename", ""),
                    "url":         meta.get("url", ""),
                    "parent_id":   meta.get("parent_id", ""),
                    "chunk_position": meta.get("chunk_position"),
                },
                rrf_score,
            ))
        return items

    # ── Core unified entrypoint ───────────────────────────────────────────────

    def query_unified(
        self,
        query: str,
        query_type: str = "factual",
        primary_domain: str | None = None,
        secondary_domain: str | None = None,
        imdb_id: str | None = None,
        person_name: str | None = None,
        top_k: int = 7,
        metadata_filters: dict | None = None,
    ) -> list[dict[str, Any]]:
        """
        Unified multi-domain retrieval with cross-encoder re-ranking.

        Pipeline:
          1. Runtime query expansion  (inject movie title / person name if known)
          2. Domain routing           (targets + quotas from query_type + keywords)
          3. Bi-Encoder recall        (BGE, per collection)
          4. Quota redistribution     (shortfalls redistributed to other collections)
          5. Cross-Encoder re-ranking (BAAI/bge-reranker-base, global)
          6. Confidence filtering     (drop score < 0.2)
          7. Top-k selection + context structuring
        """
        if not query.strip():
            return []

        # ── Step 1: Runtime query expansion ─────────────────────────────────
        expanded_query = query

        if imdb_id:
            try:
                from rag.engine.filmdb_query_engine import FilmDBQueryEngine
                engine = FilmDBQueryEngine.get_instance()
                entity = engine.entity_lookup(imdb_id)
                if entity and entity.get("title"):
                    movie_title = entity["title"]
                    # Inject title into query so book collections match it semantically
                    if movie_title.lower() not in expanded_query.lower():
                        expanded_query = f"{movie_title}. {expanded_query}"
                        logger.debug("RAGService: expanded query with title '%s'", movie_title)
            except Exception as exc:
                logger.warning("RAGService: title lookup for imdb_id '%s' failed: %s", imdb_id, exc)

        if person_name and person_name.lower() not in expanded_query.lower():
            expanded_query = f"{person_name}. {expanded_query}"
            logger.debug("RAGService: expanded query with person '%s'", person_name)

        # ── Step 2: Domain routing ───────────────────────────────────────────
        targets = _resolve_domains(expanded_query, query_type, primary_domain, secondary_domain)
        quotas  = _build_quotas(targets, query_type, total=18)

        # Legacy imdb_id filter (backward compatibility)
        imdb_filter = {"imdb_id": imdb_id} if imdb_id else None

        # Clean metadata_filters: remove None/empty values
        clean_meta_filters = {}
        if metadata_filters and isinstance(metadata_filters, dict):
            for k, v in metadata_filters.items():
                if v is not None and v != "" and v != "null":
                    clean_meta_filters[k] = v
        logger.debug("RAGService: metadata_filters=%s", clean_meta_filters or "none")

        # ── Step 3: Bi-encoder recall ───────────────────────────────────────
        q_vec = self._emb.encode_query(expanded_query).tolist()

        raw_results: dict[str, list[tuple[dict, float]]] = {}
        for col_name in targets:
            n = quotas.get(col_name, 3)
            # Build per-collection WHERE clause from metadata filters
            where = self._build_where_clause(col_name, imdb_filter, clean_meta_filters)
            # Request 3× quota up front before redistribution
            fetched = self._recall_from_collection(col_name, q_vec, n * 3, where, expanded_query)
            # FALLBACK: if filtered query returns < 2 results, retry without filter
            if where and len(fetched) < 2:
                logger.info("RAGService: filtered query on '%s' returned %d results, retrying without filter",
                            col_name, len(fetched))
                fetched = self._recall_from_collection(col_name, q_vec, n * 3, None, expanded_query)
            raw_results[col_name] = fetched

        # ── Step 4: Quota redistribution ────────────────────────────────────
        # If any collection came up short (fewer than quota), redistribute
        pool: list[tuple[dict, float]] = []
        shortfall_total = 0

        for col_name in targets:
            quota = quotas.get(col_name, 3)
            fetched = raw_results.get(col_name, [])
            # Take exactly quota items from each collection
            selected = fetched[:quota]
            pool.extend(selected)
            shortfall_total += max(0, quota - len(selected))

        # Fill shortfall from the richest collections
        if shortfall_total > 0:
            for col_name in targets:
                quota = quotas.get(col_name, 3)
                fetched = raw_results.get(col_name, [])
                extras  = fetched[quota:]  # items beyond the quota
                if extras:
                    take = min(shortfall_total, len(extras))
                    pool.extend(extras[:take])
                    shortfall_total -= take
                    if shortfall_total <= 0:
                        break

        if not pool:
            return []

        # Deduplicate on first 80 chars of passage
        seen_prefixes: set[str] = set()
        deduped_pool: list[tuple[dict, float]] = []
        for item, score in pool:
            prefix = item["passage"][:80]
            if prefix not in seen_prefixes:
                seen_prefixes.add(prefix)
                deduped_pool.append((item, score))

        # ── Step 5: Cross-encoder re-ranking ────────────────────────────────
        reranker = self._get_reranker()
        if reranker is not None and len(deduped_pool) > 1:
            passages = [item["passage"] for item, _ in deduped_pool]
            pairs    = [[expanded_query, p] for p in passages]
            try:
                rerank_scores = reranker.predict(pairs).tolist()
                # Zip back with items
                deduped_pool = [
                    (item, float(score))
                    for (item, _), score in zip(deduped_pool, rerank_scores)
                ]
            except Exception as exc:
                logger.warning("RAGService: cross-encoder predict failed: %s", exc)
                # Fall back to bi-encoder scores as-is

        # Sort by final score descending
        deduped_pool.sort(key=lambda x: x[1], reverse=True)

        # ── Step 6: Confidence filtering ─────────────────────────────────────
        CONFIDENCE_THRESHOLD = 0.0  # cross-encoder scores can be negative; keep all > 0
        if reranker is not None:
            # Cross-encoder scores: typical range [-10, 10]. Meaningful threshold ~0.
            filtered = [(item, s) for item, s in deduped_pool if s > CONFIDENCE_THRESHOLD]
        else:
            # Bi-encoder cosine similarity: threshold 0.3
            filtered = [(item, s) for item, s in deduped_pool if s >= 0.3]

        if not filtered:
            # Return best few even below threshold rather than empty
            filtered = deduped_pool[:3]

        # ── Step 7: Top-k + context structuring ──────────────────────────────
        final = []
        for item, score in filtered[:top_k]:
            # Phase 2.1: expand book chunks with ±1 window neighbours
            item = self._expand_window(item)

            domain = item.get("domain", "")


            # Build structured context label per domain type
            if domain == "plots":
                ctx_label = f"[Plot] {item.get('title', '')} ({item.get('year', '')})"
                if item.get("director"):
                    ctx_label += f" — Dir: {item['director']}"
            elif domain == "analysis":
                ctx_label = f"[Essay] {item.get('title', '')} — {item.get('source', '')}"
            elif domain in ("film_theory", "film_history", "film_criticism",
                            "film_aesthetics", "film_production", "scripts"):
                label_map = {
                    "film_theory":      "Theory",
                    "film_history":     "History",
                    "film_criticism":   "Criticism",
                    "film_aesthetics":  "Aesthetics",
                    "film_production":  "Production",
                    "scripts":          "Script",
                }
                ctx_label = f"[{label_map.get(domain, domain.title())}] {item.get('title', '')}"
                if item.get("author"):
                    ctx_label += f" — {item['author']}"
            else:
                ctx_label = f"[{domain}] {item.get('title', '')}"

            item["context_label"] = ctx_label
            item["score"] = round(float(score), 4)
            final.append(item)

        logger.info(
            "RAGService.query_unified: query_type=%s targets=%s pool=%d final=%d",
            query_type, targets, len(deduped_pool), len(final)
        )
        return final

    # ── Convenience wrappers (backward-compatible) ────────────────────────────

    def query(
        self,
        query_text: str,
        domains: list[str] | None = None,
        top_k: int = 6,
        metadata_filter: dict | None = None,
    ) -> list[dict[str, Any]]:
        """Legacy method: direct multi-collection query without re-ranking."""
        if not query_text.strip():
            return []

        if domains is None:
            domains = ["articles"]

        resolved: list[str] = []
        seen: set[str] = set()
        for d in domains:
            mapped = INTENT_DOMAIN_MAP.get(d, d)
            if mapped not in seen:
                seen.add(mapped)
                resolved.append(mapped)

        q_vec = self._emb.encode_query(query_text).tolist()
        all_results: list[tuple[dict, float]] = []

        for domain_name in resolved:
            col = self._get_collection(domain_name)
            if col is None:
                continue
            n_available = col.count()
            if n_available == 0:
                continue
            fetch = min(top_k * 3, n_available)
            try:
                results = col.query(
                    query_embeddings=[q_vec],
                    n_results=fetch,
                    where=metadata_filter,
                    include=["documents", "metadatas", "distances"],
                )
            except Exception as exc:
                logger.warning("ChromaDB query failed for '%s': %s", domain_name, exc)
                continue

            docs      = results["documents"][0]
            metas     = results["metadatas"][0]
            distances = results["distances"][0]

            for doc, meta, dist in zip(docs, metas, distances):
                score = 1.0 - dist
                all_results.append((
                    {
                        "passage":     doc,
                        "source":      meta.get("source", domain_name),
                        "entity_name": meta.get("entity_name", ""),
                        "imdb_id":     meta.get("imdb_id", ""),
                        "director":    meta.get("director", ""),
                        "cast":        meta.get("cast", ""),
                        "genre":       meta.get("genre", ""),
                        "origin":      meta.get("origin", ""),
                        "domain":      domain_name,
                        "filename":    meta.get("filename", ""),
                        "url":         meta.get("url", ""),
                        "title":       meta.get("title", ""),
                    },
                    score,
                ))

        if not all_results:
            return []

        all_results.sort(key=lambda x: x[1], reverse=True)
        final: list[dict] = []
        seen_prefixes: set[str] = set()
        for item, score in all_results:
            prefix = item["passage"][:80]
            if prefix in seen_prefixes:
                continue
            seen_prefixes.add(prefix)
            item["score"] = round(float(score), 4)
            final.append(item)
            if len(final) >= top_k:
                break
        return final

    def query_analysis(self, query: str, top_k: int = 6) -> list[dict]:
        return self.query(query, domains=["articles"], top_k=top_k)

    def query_books(self, query: str, domain: str = "film_criticism", top_k: int = 5) -> list[dict]:
        return self.query(query, domains=[domain], top_k=top_k)

    def query_plots(self, query: str, imdb_id: str | None = None, top_k: int = 5) -> list[dict]:
        filt = {"imdb_id": imdb_id} if imdb_id else None
        return self.query(query, domains=["plots"], top_k=top_k, metadata_filter=filt)

    def query_multi(self, query: str, top_k: int = 6) -> list[dict]:
        return self.query(query, domains=ALL_DOMAINS, top_k=top_k)
