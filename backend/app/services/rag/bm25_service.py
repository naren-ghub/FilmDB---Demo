import logging
import pickle
from pathlib import Path
from typing import List, Tuple
import numpy as np

logger = logging.getLogger(__name__)

class BM25Service:
    _instance = None

    def __init__(self):
        self.indices = {}
        # Path to where build_bm25_indices.py saves the pkl files
        self.indices_dir = Path(__file__).resolve().parents[4] / "rag" / "storage" / "bm25_indices"
        self._load_all_indices()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_all_indices(self):
        if not self.indices_dir.exists():
            logger.warning(f"BM25 index directory not found at {self.indices_dir}")
            return
        
        for pkl_file in self.indices_dir.glob("*.pkl"):
            col_name = pkl_file.stem
            try:
                with open(pkl_file, "rb") as f:
                    data = pickle.load(f)
                    self.indices[col_name] = data
                logger.debug(f"Loaded BM25 index for {col_name}")
            except Exception as e:
                logger.error(f"Failed to load BM25 for {col_name}: {e}")

    def query_collection(self, collection_name: str, query: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """
        Queries the BM25 index for the specified collection.
        Returns a list of tuples: (doc_id, bm25_score) sorted descending by score.
        """
        if collection_name not in self.indices:
            return []
            
        data = self.indices[collection_name]
        bm25 = data["bm25"]
        doc_ids = data["ids"]
        
        # Simple whitespace tokenization (matches what was used in builder)
        tokenized_query = query.lower().split()
        scores = bm25.get_scores(tokenized_query)
        
        top_n_indices = np.argsort(scores)[::-1][:top_k]
        
        results = []
        for idx in top_n_indices:
            score = scores[idx]
            if score > 0:  # Only include if there's actually a keyword match
                results.append((doc_ids[idx], float(score)))
                
        return results
