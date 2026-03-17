"""
D.3 — RAGService (ChromaDB backend)
=====================================
Replaces the FAISS + BM25 + RRF implementation with a ChromaDB
persistent vector store. ChromaDB provides:
  - Persistent storage (no separate metadata JSON files)
  - Built-in cosine similarity search over dense embeddings
  - Metadata filtering per collection
  - Simple add / query API

Architecture
------------
  EmbeddingService (BAAI/bge-base-en-v1.5, singleton)
        │
        ▼  encode_query()     ─ adds BGE "Represent…" prefix
  ChromaDB Collections (one per domain, persistent on disk):
    - analysis          ← film_analysis_dataset.jsonl
    - film_theory       ← 1_Film_Theory/ books
    - film_criticism    ← 2_Film_Criticism/ books
    - film_history      ← 3_Film_History/ books
    - film_aesthetics   ← 4_Film_Aesthetics/ books
    - film_production   ← 5_Film_Production/ books
    - scripts           ← 6_Scripts/ screenplays
        │
        ▼  chromadb n_results cosine
  top-k passages with metadata
        │
        ▼
  Deduplication + return

Public API (unchanged from FAISS version):
    rag = RAGService.get_instance()
    rag.query_analysis("why is Tarkovsky revered", top_k=5)
    rag.query_books("cinematography techniques", domain="film_aesthetics", top_k=5)
    rag.query("...", domains=["film_theory", "film_history"], top_k=6)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Persistent ChromaDB store lives next to the old indices folder
CHROMA_DIR = Path(__file__).resolve().parents[3] / "rag" / "chromadb_store"
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

ALL_DOMAINS = [
    "analysis",
    "film_theory",
    "film_criticism",
    "film_history",
    "film_aesthetics",
    "film_production",
    "scripts",
]

# Map intent-domain names → ChromaDB collection names
INTENT_DOMAIN_MAP: dict[str, str] = {
    "structured_data":  "analysis",
    "film_theory":      "film_theory",
    "film_criticism":   "film_criticism",
    "film_history":     "film_history",
    "film_aesthetics":  "film_aesthetics",
    "film_production":  "film_production",
    "general":          "analysis",
}


class RAGService:
    """
    Singleton — call RAGService.get_instance().
    ChromaDB collections are loaded lazily on first access per domain.
    """
    _instance: "RAGService | None" = None

    def __init__(self) -> None:
        import chromadb
        from app.services.embedding_service import EmbeddingService

        logger.info("RAGService: initialising ChromaDB client at %s", CHROMA_DIR)
        self._client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        self._emb    = EmbeddingService.get_instance()
        self._collections: dict[str, Any] = {}   # domain → chromadb.Collection

    @classmethod
    def get_instance(cls) -> "RAGService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

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

    # ── Public API (identical to FAISS version) ───────────────────────────────

    def query(
        self,
        query_text: str,
        domains: list[str] | None = None,
        top_k: int = 6,
    ) -> list[dict[str, Any]]:
        """
        Dense retrieval across one or more ChromaDB collections.

        Args:
            query_text: User's natural language query
            domains:    List of domain strings (uses INTENT_DOMAIN_MAP to resolve)
            top_k:      Max passages to return

        Returns:
            List of dicts: {passage, source, entity_name, domain, filename, url, title, score}
        """
        if not query_text.strip():
            return []

        if domains is None:
            domains = ["analysis"]

        # Resolve + deduplicate domain names
        resolved: list[str] = []
        seen: set[str] = set()
        for d in domains:
            mapped = INTENT_DOMAIN_MAP.get(d, d)
            if mapped not in seen:
                seen.add(mapped)
                resolved.append(mapped)

        # Embed query once (with BGE asymmetric prefix)
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
                    include=["documents", "metadatas", "distances"],
                )
            except Exception as exc:
                logger.warning("ChromaDB query failed for '%s': %s", domain_name, exc)
                continue

            docs      = results["documents"][0]
            metas     = results["metadatas"][0]
            distances = results["distances"][0]  # cosine distance (lower = better)

            for doc, meta, dist in zip(docs, metas, distances):
                score = 1.0 - dist   # convert distance → similarity
                all_results.append((
                    {
                        "passage":     doc,
                        "source":      meta.get("source", domain_name),
                        "entity_name": meta.get("entity_name", ""),
                        "domain":      domain_name,
                        "filename":    meta.get("filename", ""),
                        "url":         meta.get("url", ""),
                        "title":       meta.get("title", ""),
                    },
                    score,
                ))

        if not all_results:
            return []

        # Sort by similarity, deduplicate near-identical passages
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

    # ── Convenience wrappers (called by conversation_engine tool handlers) ────

    def query_analysis(self, query: str, top_k: int = 6) -> list[dict]:
        return self.query(query, domains=["analysis"], top_k=top_k)

    def query_books(self, query: str, domain: str = "film_criticism", top_k: int = 5) -> list[dict]:
        return self.query(query, domains=[domain], top_k=top_k)

    def query_multi(self, query: str, top_k: int = 6) -> list[dict]:
        return self.query(query, domains=ALL_DOMAINS, top_k=top_k)
