"""
Recommendation Engine (Combined)
=============================
Orchestrates the 3-pillar recommendation strategy and serves as the Agent Tool wrapper.
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
import os
import pandas as pd

from app.services.rag.embedding_service import EmbeddingService

# Bootstrap rag/ onto sys.path so the import works regardless of
# whether PYTHONPATH was set before launching uvicorn.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

log = logging.getLogger(__name__)

# ----------------- Core Engine -----------------
class RecommendationEngine:
    def __init__(self):
        # Lazy import after sys.path is bootstrapped above
        from kb.engine.filmdb_query_engine import FilmDBQueryEngine
        self.engine = FilmDBQueryEngine.get_instance()
        self.embedder = EmbeddingService.get_instance()
        self.collection_name = "movie_metadata"
        
        import chromadb
        from pathlib import Path
        # Adjusted path: We are in backend/app/services/kb_service/
        _APP_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
        self.chroma_client = chromadb.PersistentClient(path=str(_APP_ROOT / "rag" / "storage" / "chromadb_store"))
        
        try:
            self.col_plots = self.chroma_client.get_collection(name="plots")
        except Exception as e:
            log.warning(f"Could not load ChromaDB collection 'plots'. Error: {e}")
            self.col_plots = None

        # Cache Metadata Layer in memory for fast keywords joining & enrichment
        try:
             meta_path = str(_APP_ROOT / "rag" / "processed_dataset" / "metadata_layer.parquet")
             self.df_meta = pd.read_parquet(meta_path, columns=["imdb_id", "keywords", "tagline", "overview", "original_language", "poster_path"])
             self.df_meta.set_index("imdb_id", inplace=True, drop=False)
        except Exception as e:
             log.warning(f"Could not load metadata_layer: {e}")
             self.df_meta = pd.DataFrame()

    def recommend(
        self, 
        profile: str, 
        query: Optional[str] = None, 
        imdb_id: Optional[str] = None, 
        top_n: int = 15
    ) -> Dict[str, Any]:
        candidates: dict[str, dict] = {}
        collab_results = {}
        target_tags = set()
        shared_tags_map = {}
        
        if imdb_id:
            collab_results, target_tags, shared_tags_map = self._get_collaborative_scores(imdb_id)
            for cid, score in collab_results.items():
                candidates[cid] = {"collab_score": score}
        else:
            if query:
                df = self.engine._recommendations
                if df is not None:
                    mask = df["overview"].fillna("").str.lower().str.contains(query.lower()) | \
                           df["ml_tags"].fillna("").str.lower().str.contains(query.lower())
                    match_df = df[mask].head(50)
                    for _, row in match_df.iterrows():
                        candidates[row["imdb_id"]] = {"collab_score": 0.3}
        
        scored_movies = []
        sorted_candidates = sorted(candidates.items(), key=lambda x: x[1].get("collab_score", 0.0), reverse=True)[:500]
        
        for cid, scores in sorted_candidates:
            l_score = scores.get("collab_score", 0.0)
            ranking = self._get_ranking_signals(cid)
            if not ranking: continue
                
            r_rating = ranking.get("rating_norm", 0.0)
            r_pop = ranking.get("popularity_norm", 0.0)
            r_recency = ranking.get("recency_norm", 0.0)

            final_score = 0.0
            if profile == "SIMILARITY":
                final_score = l_score + (0.1 * r_rating)
            elif profile == "GENRE_TOP" or profile == "POPULAR":
                final_score = (0.5 * r_rating) + (0.3 * r_pop) + (0.2 * r_recency)
            elif profile == "UNDERRATED":
                final_score = l_score + (0.4 * r_rating) - (0.4 * r_pop)
            else:
                final_score = l_score

            genre_overlap = []
            if imdb_id:
                target_genres = (self.engine.entity_lookup(imdb_id).get("genres") or "").split(",")
                cand_genres = (ranking.get("genres") or "").split(",")
                genre_overlap = list(set(target_genres) & set(cand_genres))
                if not genre_overlap:
                    final_score *= 0.7
                    
            scored_movies.append({
                "imdb_id": cid,
                "title": ranking.get("title", "Unknown"),
                "year": ranking.get("year", ""),
                "rating": ranking.get("rating", 0),
                "popularity": ranking.get("popularity_raw", 0),
                "genres": ranking.get("genres", ""),
                "final_score": round(final_score, 3),
                "signals": {
                    "content": 0.0,
                    "collaborative": round(l_score, 3),
                    "ranking": round(r_rating, 3)
                },
                "shared_tags": shared_tags_map.get(cid, []) if imdb_id else []
            })

        scored_movies.sort(key=lambda x: x["final_score"], reverse=True)
        top_matches = scored_movies[:top_n]
        if imdb_id:
            top_matches = [m for m in top_matches if m["imdb_id"] != imdb_id]
        
        meta_df = getattr(self, "df_meta", pd.DataFrame())

        for m in top_matches:
            ent = self.engine.entity_lookup(m["imdb_id"])
            if ent:
                m["poster_path"] = ent.get("poster_path")
                m["overview"] = ent.get("overview")
            
            if not meta_df.empty:
                try:
                    match = meta_df.loc[m["imdb_id"]]
                    m["overview"] = match.get("overview") or m.get("overview", "")
                    m["keywords"] = match.get("keywords", "")
                    m["original_language"] = match.get("original_language", "")
                    if not m.get("poster_path") and match.get("poster_path"):
                         m["poster_path"] = match.get("poster_path")
                except KeyError:
                    pass

        return {
            "query_profile": profile,
            "anchor_id": imdb_id,
            "recommendation_count": len(top_matches),
            "recommendations": top_matches
        }

    def _get_content_scores(self, query: Optional[str], imdb_id: Optional[str], fetch_k: int = 50) -> Dict[str, float]:
        scores_map = {}
        search_text = query or ""
        if imdb_id and not query:
            ent = self.engine.entity_lookup(imdb_id)
            if ent and ent.get("overview"):
                search_text = f"Title: {ent.get('title')}\nOverview: {ent.get('overview')}\nKeywords: {ent.get('keywords', '')}"

        if not search_text: return scores_map
        query_embeddings = [self.embedder.encode_query(search_text).tolist()]

        def _fetch_from_col(collection) -> Dict[str, float]:
            if not collection: return {}
            results = collection.query(query_embeddings=query_embeddings, n_results=fetch_k)
            local_scores = {}
            if results and results["ids"] and results["ids"][0]:
                for doc_id, meta, dist in zip(results["ids"][0], results["metadatas"][0], results["distances"][0]):
                    mid = meta.get("imdb_id")
                    if not mid: continue
                    sim = max(0.0, min(1.0, 1.0 - (dist / 2.0)))
                    local_scores[mid] = max(sim, local_scores.get(mid, 0.0))
            return local_scores

        return _fetch_from_col(self.col_plots)

    def _get_collaborative_scores(self, target_imdb_id: str) -> tuple[Dict[str, float], set, Dict[str, set]]:
        df = self.engine._recommendations
        if df is None: return {}, set(), {}

        meta_df = getattr(self, "df_meta", pd.DataFrame())
        df_copy = df.copy()
        if not meta_df.empty:
             df_copy = df_copy.merge(meta_df[["imdb_id", "keywords", "tagline"]], on="imdb_id", how="left")
             
        df_copy["combined_tags"] = (
            df_copy["ml_tags"].fillna("") + "|" + 
            df_copy["keywords"].fillna("").astype(str).str.replace(", ", "|", regex=False) + "|" +
            df_copy["tagline"].fillna("").astype(str)
        )

        target_row = df_copy[df_copy["imdb_id"] == target_imdb_id]
        if target_row.empty: return {}, set(), {}

        target_tags_str = str(target_row.iloc[0]["combined_tags"]).lower()
        target_tags = {t.strip() for t in target_tags_str.split("|") if t.strip() and t.strip() != "nan"}

        generic_tags = {"dvd", "bluray", "netflix", "imax", "uhd", "movie", "film"}
        scores_map = {}
        shared_tags_map = {}

        df_copy["temp_tags"] = df_copy["combined_tags"].fillna("").astype(str).str.lower().str.split("|")
        df_copy["overlap"] = df_copy["temp_tags"].apply(lambda x: set(x) & target_tags)
        df_copy["overlap_len"] = df_copy["overlap"].apply(len)
        
        active_df = df_copy[df_copy["overlap_len"] > 0]
        for _, row in active_df.iterrows():
            cid = row["imdb_id"]
            if cid == target_imdb_id: continue
                
            overlap = row["overlap"]
            raw_score = sum(0.2 if t in generic_tags else 1.0 for t in overlap)
            scores_map[cid] = min(1.0, raw_score / 10.0) 
            shared_tags_map[cid] = list(overlap)
            
        return scores_map, target_tags, shared_tags_map

    def _get_ranking_signals(self, imdb_id: str) -> Dict[str, Any]:
        ent = self.engine.entity_lookup(imdb_id)
        if not ent: return {}
            
        r_val = float(ent.get("imdb_rating") or ent.get("vote_average") or 0.0)
        rating_norm = r_val / 10.0 
        
        import math
        votes = float(ent.get("vote_count") or ent.get("imdb_votes") or 0.0)
        pop_norm = min(1.0, math.log10(max(1, votes)) / 6.0) if votes > 0 else 0.0
        
        year_str = str(ent.get("year", "0")).split("-")[0]
        year = int(year_str) if year_str.isdigit() else 2000
        recent_norm = max(0.0, 1.0 - ((2026 - year) / 50.0))
        
        return {
            "title": ent.get("title"), "year": year, "rating": r_val, "popularity_raw": votes,
            "genres": ent.get("genres", ""), "rating_norm": rating_norm,
            "popularity_norm": pop_norm, "recency_norm": recent_norm
        }

# ----------------- LLM Tool Adapter -----------------
_service_instance = None

def get_service() -> RecommendationEngine:
    global _service_instance
    if _service_instance is None:
        _service_instance = RecommendationEngine()
    return _service_instance

async def run(query: str = "", imdb_id: Optional[str] = None, profile: str = "SIMILARITY") -> dict:
    """Retrieves highly-tuned movie recommendations using the local Engine."""
    logger = logging.getLogger(__name__)
    logger.info(f"recommendation_engine.run() called. profile='{profile}', imdb_id='{imdb_id}'")
    
    if profile not in ["SIMILARITY", "GENRE_TOP", "UNDERRATED"]:
        profile = "SIMILARITY"
    
    service = get_service()
    try:
         result = service.recommend(profile=profile, query=query, imdb_id=imdb_id, top_n=10)
         recs = result.get("recommendations", [])
         if not recs:
             return {"status": "not_found", "data": {"query": query, "profile": profile}}
         result["recommendation_titles"] = [r.get("title", "Unknown") for r in recs if r.get("title")]
         return {"status": "success", "data": result}
    except Exception as e:
         logger.error(f"Error in RecommendationEngine tool: {e}", exc_info=True)
         return {"status": "error", "error": str(e)}

