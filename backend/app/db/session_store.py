from datetime import datetime
from typing import Any, Dict, cast

from sqlalchemy.orm import Session

from app.db.models import Message, SessionContext, SessionLocal, ToolCall, User, UserProfile
from app.db.models import Session as ChatSession


def get_db() -> Session:
    return SessionLocal()


def get_or_create_user(db: Session, user_id: str) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        return user
    user = User(id=user_id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_or_create_session(db: Session, session_id: str, user_id: str) -> ChatSession:
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if session:
        return session
    session = ChatSession(
        id=session_id,
        user_id=user_id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def fetch_last_messages(db: Session, session_id: str, limit: int = 8) -> list[Message]:
    return (
        db.query(Message)
        .filter(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
        .all()
    )


def store_message(
    db: Session, session_id: str, role: str, content: str, token_count: int | None = None
) -> Message:
    message = Message(
        session_id=session_id,
        role=role,
        content=content,
        token_count=token_count,
        created_at=datetime.utcnow(),
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def store_tool_call(
    session_id: str,
    tool_name: str,
    request_payload: Dict[str, Any],
    response_status: str,
    execution_time_ms: int,
) -> ToolCall:
    db = SessionLocal()
    try:
        tool_call = ToolCall(
            session_id=session_id,
            tool_name=tool_name,
            request_payload=request_payload,
            response_status=response_status,
            execution_time_ms=execution_time_ms,
            created_at=datetime.utcnow(),
        )
        db.add(tool_call)
        db.commit()
        db.refresh(tool_call)
        return tool_call
    finally:
        db.close()


def get_user_profile(db: Session, user_id: str) -> UserProfile | None:
    return db.query(UserProfile).filter(UserProfile.user_id == user_id).first()


def get_session_context(db: Session, session_id: str) -> SessionContext | None:
    return db.query(SessionContext).filter(SessionContext.session_id == session_id).first()


def upsert_session_context(
    db: Session,
    session_id: str,
    last_movie: str | None,
    last_person: str | None,
    last_entity: str | None,
    entity_type: str | None,
    last_intent: str | None,
) -> SessionContext:
    ctx = db.query(SessionContext).filter(SessionContext.session_id == session_id).first()
    if ctx:
        cast(Any, ctx).last_movie = last_movie
        cast(Any, ctx).last_person = last_person
        cast(Any, ctx).last_entity = last_entity
        cast(Any, ctx).entity_type = entity_type
        cast(Any, ctx).last_intent = last_intent
        cast(Any, ctx).updated_at = datetime.utcnow()
    else:
        ctx = SessionContext(
            session_id=session_id,
            last_movie=last_movie,
            last_person=last_person,
            last_entity=last_entity,
            entity_type=entity_type,
            last_intent=last_intent,
            updated_at=datetime.utcnow(),
        )
        db.add(ctx)
    db.commit()
    db.refresh(ctx)
    return ctx
