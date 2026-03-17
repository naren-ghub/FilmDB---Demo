import os

from dotenv import load_dotenv

load_dotenv(override=True)

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
    HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "15"))

settings = Settings()
