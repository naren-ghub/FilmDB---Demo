import json
from datetime import datetime
from typing import Any, Dict, cast

import bcrypt
from sqlalchemy.orm import Session

from app.db.models import (
    ChatSession,
    Message,
    RequestLog,
    SessionContext,
    SessionLocal,
    ToolCall,
    User,
    UserProfile,
)



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
    entity_stack: list | str | None = None,
    covered_categories: list | str | None = None,
) -> SessionContext:
    ctx = db.query(SessionContext).filter(SessionContext.session_id == session_id).first()
    if ctx:
        cast(Any, ctx).last_movie = last_movie
        cast(Any, ctx).last_person = last_person
        cast(Any, ctx).last_entity = last_entity
        cast(Any, ctx).entity_type = entity_type
        cast(Any, ctx).last_intent = last_intent
        if entity_stack is not None:
            cast(Any, ctx).entity_stack = entity_stack
        if covered_categories is not None:
            cast(Any, ctx).covered_categories = covered_categories
        cast(Any, ctx).updated_at = datetime.utcnow()
    else:
        ctx = SessionContext(
            session_id=session_id,
            last_movie=last_movie,
            last_person=last_person,
            last_entity=last_entity,
            entity_type=entity_type,
            last_intent=last_intent,
            entity_stack=entity_stack,
            covered_categories=covered_categories,
            updated_at=datetime.utcnow(),
        )
        db.add(ctx)
    db.commit()
    db.refresh(ctx)
    return ctx


# ─────────── Auth CRUD ────────────────────────────────────────────────────────

def _hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())


def _verify_password(password: str, hashed: str | bytes) -> bool:
    if isinstance(hashed, str):
        hashed = hashed.encode("utf-8")
    return bcrypt.checkpw(password.encode("utf-8"), hashed)


def register_user(db: Session, username: str, password: str) -> User | None:
    """Create a new user. Returns None if the username already exists."""
    key = username.lower()
    existing = db.query(User).filter(User.id == key).first()
    if existing:
        return None
    user = User(
        id=key,
        username=username,          # case-preserved display name
        password_hash=_hash_password(password).decode("utf-8"),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    """Return the User if credentials are valid, else None."""
    user = db.query(User).filter(User.id == username.lower()).first()
    if not user:
        return None
    ph = getattr(user, "password_hash", None)
    if not ph:
        return None
    return user if _verify_password(password, ph) else None


def user_exists_db(db: Session, username: str) -> bool:
    return db.query(User).filter(User.id == username.lower()).first() is not None


def save_profile_db(db: Session, username: str, profile: Dict[str, Any]) -> None:
    """Upsert the user profile with aligned field names."""
    key = username.lower()
    existing = db.query(UserProfile).filter(UserProfile.user_id == key).first()
    if existing:
        for field in ["region", "platforms", "genres", "fav_movies", "fav_actors", "fav_directors", "watchlist", "favorites"]:
            if field in profile:
                setattr(existing, field, profile[field])
        cast(Any, existing).updated_at = datetime.utcnow()
    else:
        existing = UserProfile(
            user_id=key,
            region=profile.get("region"),
            platforms=profile.get("platforms"),
            genres=profile.get("genres"),
            fav_movies=profile.get("fav_movies"),
            fav_actors=profile.get("fav_actors"),
            fav_directors=profile.get("fav_directors"),
            watchlist=profile.get("watchlist"),
            favorites=profile.get("favorites"),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(existing)
    db.commit()


def get_profile_db(db: Session, username: str) -> Dict[str, Any] | None:
    """Return profile dict or None if not yet set."""
    prof = db.query(UserProfile).filter(UserProfile.user_id == username.lower()).first()
    if not prof:
        return None
    return {
        "region": prof.region,
        "platforms": prof.platforms or [],
        "genres": prof.genres or [],
        "fav_movies": prof.fav_movies or [],
        "fav_actors": prof.fav_actors or [],
        "fav_directors": prof.fav_directors or [],
        "watchlist": prof.watchlist or [],
        "favorites": prof.favorites or [],
    }


import json

def save_chat_sessions_db(db: Session, username: str, sessions: dict) -> None:
    """Persist all chat sessions for a user (upsert session title + messages)."""
    key = username.lower()
    items = list(sessions.items())
    for sid, sdata in items:
        chat_session = db.query(ChatSession).filter(ChatSession.id == sid).first()
        if not chat_session:
            chat_session = ChatSession(
                id=sid,
                user_id=key,
                title=sdata.get("title", ""),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(chat_session)
        else:
            cast(Any, chat_session).title = sdata.get("title", chat_session.title)
            cast(Any, chat_session).updated_at = datetime.utcnow()
            
        # Sync messages for this session
        if "messages" in sdata and len(sdata["messages"]) == 0:
            db.query(Message).filter(Message.session_id == sid).delete()
    db.commit()

def get_chat_sessions_db(db: Session, username: str) -> dict:
    """Return all chat sessions for a user as a dict keyed by session_id."""
    key = username.lower()
    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == key)
        .filter(ChatSession.deleted_at == None) # Skip Recycle Bin
        .order_by(ChatSession.created_at.desc())
        .limit(100)
        .all()
    )
    result = {}
    for s in sessions:
        # Fetch latest messages for this session
        msgs = (
            db.query(Message)
            .filter(Message.session_id == s.id)
            .order_by(Message.created_at.asc())
            .all()
        )
        msg_list = []
        for m in msgs:
            msg_dict = {"role": m.role, "content": m.content}
            if m.role == "assistant":
                try:
                    parsed = json.loads(m.content)
                    if isinstance(parsed, dict):
                        msg_dict.update(parsed)
                        if "text_response" not in msg_dict:
                            msg_dict["text_response"] = parsed.get("content", m.content)
                    else:
                        msg_dict["text_response"] = str(parsed)
                except Exception:
                    msg_dict["text_response"] = m.content
            msg_list.append(msg_dict)
            
        result[s.id] = {
            "title": s.title or "",
            "messages": msg_list,
        }
    return result


def soft_delete_session_db(db: Session, session_id: str) -> bool:
    """Move a session to the Recycle Bin."""
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if session:
        cast(Any, session).deleted_at = datetime.utcnow()
        db.commit()
        return True
    return False


def restore_session_db(db: Session, session_id: str) -> bool:
    """Restore a session from the Recycle Bin."""
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if session:
        cast(Any, session).deleted_at = None
        db.commit()
        return True
    return False


def get_deleted_chat_sessions_db(db: Session, username: str) -> dict:
    """Return sessions currently in the Recycle Bin (deleted within last 3 days)."""
    from datetime import timedelta
    three_days_ago = datetime.utcnow() - timedelta(days=3)
    
    key = username.lower()
    sessions = (
        db.query(ChatSession)
        .filter(ChatSession.user_id == key)
        .filter(ChatSession.deleted_at != None)
        .filter(ChatSession.deleted_at >= three_days_ago)
        .order_by(ChatSession.deleted_at.desc())
        .all()
    )
    
    result = {}
    for s in sessions:
        result[s.id] = {
            "title": s.title if (s.title and s.title.strip()) else "Untitled Conversation",
            "deleted_at": s.deleted_at.isoformat() if s.deleted_at else None
        }
    return result


def hard_delete_expired_sessions_db(db: Session) -> int:
    """Permanently delete sessions that have been in Recycle Bin for > 3 days."""
    from datetime import timedelta
    three_days_ago = datetime.utcnow() - timedelta(days=3)
    
    expired = (
        db.query(ChatSession)
        .filter(ChatSession.deleted_at != None)
        .filter(ChatSession.deleted_at < three_days_ago)
        .all()
    )
    
    count = 0
    for s in expired:
        # Delete dependent messages first (SQLAlchemy Cascade would be better but let's be safe)
        db.query(Message).filter(Message.session_id == s.id).delete()
        db.query(ToolCall).filter(ToolCall.session_id == s.id).delete()
        db.query(SessionContext).filter(SessionContext.session_id == s.id).delete()
        db.query(RequestLog).filter(RequestLog.session_id == s.id).delete()
        db.delete(s)
        count += 1
    
    if count > 0:
        db.commit()
    return count


# ─────────── Request Trace Logging ────────────────────────────────────────────

def log_request(
    trace: Dict[str, Any], 
    response: Dict[str, Any], 
    total_time_ms: int = 0,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    token_breakdown: Dict[str, Any] | None = None,
    llm_call_count: int | None = None,
    tool_outputs: Dict[str, Any] | None = None
) -> None:
    """Persist the full query-to-response trace to the request_logs table."""
    db = SessionLocal()
    try:
        intent = trace.get("intent", {})
        routing = trace.get("tool_selector", {})
        tool_exec = trace.get("tool_execution", {})
        er = trace.get("entity_resolution", {})
        approved = [c.get("name") for c in trace.get("tool_calls_approved", []) if isinstance(c, dict)]
        rejected = [c.get("name") for c in trace.get("tool_calls_rejected", []) if isinstance(c, dict)]

        shadow = trace.get("shadow_intent") or {}
        entry = RequestLog(
            session_id=trace.get("session_id"),
            user_id=trace.get("user_id"),
            user_message=trace.get("message", ""),
            resolved_message=trace.get("resolved_message", ""),
            primary_intent=intent.get("primary_intent"),
            intent_confidence=intent.get("confidence"),
            entities=intent.get("entities"),
            entity_type=er.get("entity_type"),
            entity_value=er.get("entity_value"),
            required_tools=routing.get("required"),
            optional_tools=routing.get("optional"),
            approved_tools=approved,
            rejected_tools=rejected,
            tool_timings=tool_exec.get("tool_timings"),
            cache_hits=tool_exec.get("cache_hits"),
            cache_misses=tool_exec.get("cache_misses"),
            response_mode=response.get("response_mode"),
            text_response=response.get("text_response", ""),
            response_json=response,
            session_context_before=trace.get("session_context_before"),
            session_context_after=trace.get("session_context_after"),
            total_time_ms=total_time_ms,
            error=str(trace.get("fatal_error")) if trace.get("fatal_error") else None,
            # C.4 — Shadow mode: HybridIntentClassifier parallel results
            shadow_domain=shadow.get("domain"),
            shadow_intent=shadow.get("intent"),
            shadow_confidence=shadow.get("confidence"),
            # Factual Tokens (Phase 10)
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            token_breakdown=token_breakdown,
            llm_call_count=llm_call_count,
            tool_outputs=tool_outputs,
            created_at=datetime.utcnow(),
        )
        db.add(entry)
        db.commit()
    except Exception:
        pass
    finally:
        db.close()

