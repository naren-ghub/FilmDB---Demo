# FilmDB Demo - Environment & Deployment Architecture

------------------------------------------------------------------------

# 1. Introduction

This document defines the complete environment configuration and
deployment architecture for the FilmDB - Demo backend.

It explains:

-   Environment variable management
-   API key handling
-   Project configuration structure
-   Development setup
-   Docker deployment
-   Production architecture
-   Security practices
-   Scaling considerations

------------------------------------------------------------------------

# 2. Environment Configuration Philosophy

We strictly separate:

-   Code
-   Secrets
-   Runtime configuration
-   Infrastructure

API keys are stored in:

.env

RapidAPI example snippets are stored in:

code_snippets.txt

Rules:

-   Never commit .env to version control
-   Never hardcode secrets
-   Never expose secrets to frontend
-   Load environment variables at startup

------------------------------------------------------------------------

# 3. Example .env File

``` env
# RapidAPI
RAPIDAPI_KEY=your_rapidapi_key
IMDB_HOST=imdb8.p.rapidapi.com
SIMILARITY_HOST=movie-similarity.p.rapidapi.com

# Watchmode
WATCHMODE_API_KEY=your_watchmode_key

# Web Search
SERPER_API_KEY=your_serper_key

# LLM Provider
LLM_API_KEY=your_llm_api_key

# Database
DATABASE_URL="sqlite:///./FilmDB_Demo.db"

# App
ENVIRONMENT=development
```

------------------------------------------------------------------------

# 4. Configuration Loader Module

Create config.py:

``` python
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
    WATCHMODE_API_KEY = os.getenv("WATCHMODE_API_KEY")
    SERPER_API_KEY = os.getenv("SERPER_API_KEY")
    LLM_API_KEY = os.getenv("LLM_API_KEY")
    DATABASE_URL = os.getenv("DATABASE_URL")
    ENVIRONMENT = os.getenv("ENVIRONMENT")

settings = Settings()
```

All services must import settings from this file.

------------------------------------------------------------------------

# 5. Project Structure

    FilmDB_Demo/
    architecture/
        ├── architecture_Documentation_files
    backend/
    ├── app/
    │   ├── main.py
    │   ├── config.py
    │   ├── conversation_engine.py
    │   ├── governance.py
    │   │
    │   ├── services/
    │   │   ├── imdb_service.py
    │   │   ├── wikipedia_service.py
    │   │   ├── watchmode_service.py
    │   │   ├── similarity_service.py
    │   │   ├── archive_service.py
    │   │   ├── web_search_service.py
    │   │
    │   ├── db/
    │   │   ├── models.py
    │   │   ├── session_store.py
    │   │   ├── cache_layer.py
    │   │
    │   └── utils/
    │       ├── prompt_builder.py
    │       ├── tool_formatter.py
    │
    ├── .env
    ├── code_snippets.txt
    ├── requirements.txt
    └── README.md

** Note: Project Structe may change as development progresses. Always refer to the latest documentation for accurate structure. **

------------------------------------------------------------------------

# 6. Development Setup

Steps:

1.  Create virtual environment
2.  Install dependencies

``` bash
pip install -r requirements.txt
```

3.  Create .env file
4.  Start server

``` bash
uvicorn app.main:app --reload
```

------------------------------------------------------------------------


# 7. API Key Security

Security rules:

-   Backend-only tool execution
-   Never log secrets
-   Set provider usage quotas
-   Rotate keys periodically
-   Monitor unusual usage
-   Restrict CORS properly

------------------------------------------------------------------------


# 8. Observability

Log:

-   Tool calls
-   Execution time
-   Token usage
-   Errors

Never log secrets.

Use structured logging format (JSON logs).

------------------------------------------------------------------------

# Final Deployment Philosophy

Secrets live in .env RapidAPI snippets live in code_snippets.txt Backend
owns execution Frontend never sees keys

This separation ensures:

-   Security
-   Modularity
-   Reproducibility
-   Scalability
-   Production readiness


** Additonal Information The Architecture documentation are stored in the architecture folder. Please refer to them for detailed design explanations. If any changes detected in those files go through the proper review process. If any archietectural change happens while coding update the documentation accordingly, by appending changes happened to the appropriate documentation file with date and time stamp.**

------------------------------------------------------------------------

# Update Log

**2026-02-28 22:40 UTC**

- Added optional `TMDB_API_KEY` for TMDB-based similarity recommendations.
- Added `HTTP_TIMEOUT_SECONDS` for outbound tool request timeouts.
