
import logging
import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# BGE-base-en-v1.5: 768-dim, MTEB rank ~30. Drop-in upgrade from bge-small.
# BGE asymmetric retrieval: queries get a prefix, passages do not.
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

class EmbeddingService:
    """
    Singleton loader for BAAI/bge-base-en-v1.5.
    Used by DomainClassifier, RAGService, and ingest scripts so the
    entire system shares ONE model instance and ONE embedding space.
    """
    _instance: "EmbeddingService | None" = None
    _model: SentenceTransformer | None = None
    MODEL_NAME = "BAAI/bge-base-en-v1.5"

    def __init__(self) -> None:
        if EmbeddingService._instance is not None:
            raise RuntimeError("Use EmbeddingService.get_instance()")

    @classmethod
    def get_instance(cls) -> "EmbeddingService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info("EmbeddingService: loading %s on %s …", self.MODEL_NAME, device.upper())
            self._model = SentenceTransformer(self.MODEL_NAME, device=device)
        return self._model

    def encode_query(self, text: str) -> np.ndarray:
        """Encode a user query with BGE asymmetric prefix. Returns L2-normalised float32 array."""
        return self.model.encode(
            _QUERY_PREFIX + text,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        ).astype("float32")

    def encode_passages(self, texts: list[str], batch_size: int = 256) -> np.ndarray:
        """Encode a list of passages (no prefix). Returns (N, dim) float32 matrix.
        Automatically uses GPU if available — batch_size doubles on CUDA."""
        import torch
        if torch.cuda.is_available():
            batch_size = batch_size * 2   # GPU can handle larger batches
        return self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=batch_size,
            convert_to_numpy=True,
        ).astype("float32")
