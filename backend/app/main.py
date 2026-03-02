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


@app.post("/chat")
async def chat(request: ChatRequest):
    return await engine.run(request.session_id, request.user_id, request.message)
