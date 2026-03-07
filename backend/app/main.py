from fastapi import FastAPI
from pydantic import BaseModel

from app.conversation_engine import ConversationEngine
from app.db.models import init_db

app = FastAPI(title="FilmDB Demo")
engine = ConversationEngine()


class ChatRequest(BaseModel):
    session_id: str
    user_id: str
    message: str


@app.on_event("startup")
def startup() -> None:
    init_db()
    # Eager-load parquet data so the first request isn't slow
    import logging
    log = logging.getLogger(__name__)
    log.info("Eager-loading FilmDBQueryEngine …")
    try:
        from rag.filmdb_query_engine import FilmDBQueryEngine
        FilmDBQueryEngine.get_instance()
        log.info("FilmDBQueryEngine ready.")
    except Exception:
        log.exception("Failed to pre-load FilmDBQueryEngine — KB tools will retry lazily")


@app.post("/chat")
async def chat(request: ChatRequest):
    return await engine.run(request.session_id, request.user_id, request.message)
