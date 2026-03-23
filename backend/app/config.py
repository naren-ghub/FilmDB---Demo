import os

from dotenv import load_dotenv

load_dotenv(override=True)

# ── Model Cache Directory ─────────────────────────────────────────────────────
# All sentence-transformers and HuggingFace models (bi-encoder, cross-encoder,
# future models) are cached here so they're shared across projects on this machine.
# Default: C:\Models\huggingface (can be overridden in .env via MODEL_CACHE_DIR)
import os as _os
_MODEL_CACHE = _os.getenv("MODEL_CACHE_DIR", r"C:\Models\huggingface")
_os.environ.setdefault("HF_HOME",                   _MODEL_CACHE)
_os.environ.setdefault("TRANSFORMERS_CACHE",         _MODEL_CACHE)
_os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", _MODEL_CACHE)
# ─────────────────────────────────────────────────────────────────────────────

class Settings:
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    GROQ_RESPONSE_API_KEY = os.getenv("GROQ_RESPONSE_API_KEY")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3-32b")
    # Calculate project root (assuming this file is in backend/app/config.py)
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _DB_NAME = "FilmDB_Demo.db"
    _ABS_DB_PATH = os.path.join(BASE_DIR, _DB_NAME)
    
    DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{_ABS_DB_PATH}")
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
    RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
    IMDB_HOST = os.getenv("IMDB_HOST", "imdb8.p.rapidapi.com")
    IMDB236_HOST = os.getenv("IMDB236_HOST", "imdb236.p.rapidapi.com")
    IMDB232_HOST = os.getenv("IMDB232_HOST", "imdb232.p.rapidapi.com")
    WATCHMODE_API_KEY = os.getenv("WATCHMODE_API_KEY")
    SERPER_API_KEY = os.getenv("SERPER_API_KEY")
    TMDB_API_KEY = os.getenv("TMDB_API_KEY")
    TASTEDIVE_API_KEY = os.getenv("TASTEDRIVE_API_KEY")  # Bridges TasteDrive typo from .env
    EMBED_API_URL = os.getenv("EMBED_API_URL", "https://api.2embed.cc")
    EMBED_BASE_URL = os.getenv("EMBED_BASE_URL", "https://www.2embed.cc")
    HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "15"))

settings = Settings()
