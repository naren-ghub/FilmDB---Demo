import os

from dotenv import load_dotenv

load_dotenv(override=True)

class Settings:
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./FilmDB_Demo.db")
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
