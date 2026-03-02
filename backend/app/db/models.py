import uuid
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

Base = declarative_base()

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_uuid)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now)


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id = Column(String, ForeignKey("users.id"), primary_key=True)
    region = Column(String)
    preferred_language = Column(String)
    subscribed_platforms = Column(JSON)
    favorite_genres = Column(JSON)
    favorite_movies = Column(JSON)
    response_style = Column(String)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now)


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"))
    title = Column(String)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now)


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=_uuid)
    session_id = Column(String, ForeignKey("sessions.id"))
    role = Column(String)
    content = Column(Text)
    token_count = Column(Integer)
    created_at = Column(DateTime, default=_now)


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id = Column(String, primary_key=True, default=_uuid)
    session_id = Column(String, ForeignKey("sessions.id"))
    tool_name = Column(String)
    request_payload = Column(JSON)
    response_status = Column(String)
    execution_time_ms = Column(Integer)
    created_at = Column(DateTime, default=_now)


class MovieMetadataCache(Base):
    __tablename__ = "movie_metadata_cache"

    title = Column(String, primary_key=True)
    imdb_data = Column(JSON)
    wikipedia_data = Column(JSON)
    cached_at = Column(DateTime, default=_now)


class StreamingCache(Base):
    __tablename__ = "streaming_cache"

    title = Column(String, primary_key=True)
    region = Column(String, primary_key=True)
    streaming_data = Column(JSON)
    cached_at = Column(DateTime, default=_now)


class SimilarityCache(Base):
    __tablename__ = "similarity_cache"

    title = Column(String, primary_key=True)
    recommendations = Column(JSON)
    cached_at = Column(DateTime, default=_now)


class SessionContext(Base):
    __tablename__ = "session_context"

    session_id = Column(String, primary_key=True)
    last_movie = Column(String)
    last_person = Column(String)
    last_entity = Column(String)
    entity_type = Column(String)
    last_intent = Column(String)
    updated_at = Column(DateTime, default=_now)


class QueryAnalytics(Base):
    __tablename__ = "query_analytics"

    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String)
    session_id = Column(String)
    query_text = Column(Text)
    tools_used = Column(JSON)
    response_time_ms = Column(Integer)
    created_at = Column(DateTime, default=_now)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_session_context_columns()


def _ensure_session_context_columns() -> None:
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    with engine.connect() as conn:
        try:
            result = conn.exec_driver_sql("PRAGMA table_info(session_context)")
        except Exception:
            return
        rows = result.fetchall()
        if not rows:
            return
        existing = {row[1] for row in rows}
        if "last_entity" not in existing:
            conn.exec_driver_sql("ALTER TABLE session_context ADD COLUMN last_entity TEXT")
        if "entity_type" not in existing:
            conn.exec_driver_sql("ALTER TABLE session_context ADD COLUMN entity_type TEXT")
        conn.commit()
