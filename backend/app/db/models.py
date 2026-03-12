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
    username = Column(String, unique=True, nullable=True)   # display username (case-preserved)
    password_hash = Column(String, nullable=True)           # bcrypt hash
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now)


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id = Column(String, ForeignKey("users.id"), primary_key=True)
    region = Column(String)
    # Field names aligned with frontend personalization form
    platforms = Column(JSON)       # formerly subscribed_platforms
    genres = Column(JSON)          # formerly favorite_genres
    fav_movies = Column(JSON)      # formerly favorite_movies
    fav_actors = Column(JSON)      # NEW — collected by frontend but previously ignored
    fav_directors = Column(JSON)   # NEW — collected by frontend but previously ignored
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


class RequestLog(Base):
    """Full query-to-response trace for admin review and validation."""
    __tablename__ = "request_logs"

    id = Column(String, primary_key=True, default=_uuid)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=True)
    user_id = Column(String, nullable=True)

    # ── Request ──
    user_message = Column(Text)
    resolved_message = Column(Text)       # after pronoun resolution

    # ── Intent ──
    primary_intent = Column(String)
    intent_confidence = Column(Integer)
    entities = Column(JSON)

    # ── Entity Resolution ──
    entity_type = Column(String)          # "movie" | "person"
    entity_value = Column(String)

    # ── Routing & Tools ──
    required_tools = Column(JSON)
    optional_tools = Column(JSON)
    approved_tools = Column(JSON)
    rejected_tools = Column(JSON)
    tool_timings = Column(JSON)           # [{tool, status, time_ms, error}]
    cache_hits = Column(JSON)
    cache_misses = Column(JSON)

    # ── Response ──
    response_mode = Column(String)
    text_response = Column(Text)
    response_json = Column(JSON)          # full response dict

    # ── Context ──
    session_context_before = Column(JSON)
    session_context_after = Column(JSON)

    # ── Metadata ──
    total_time_ms = Column(Integer)
    error = Column(Text)                  # populated if a fatal error occurred
    created_at = Column(DateTime, default=_now)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_session_context_columns()
    _ensure_user_columns()
    _ensure_user_profile_columns()


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


def _ensure_user_columns() -> None:
    """Migrate existing users table to include username and password_hash."""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    with engine.connect() as conn:
        try:
            result = conn.exec_driver_sql("PRAGMA table_info(users)")
            existing = {row[1] for row in result.fetchall()}
            if "username" not in existing:
                conn.exec_driver_sql("ALTER TABLE users ADD COLUMN username TEXT")
            if "password_hash" not in existing:
                conn.exec_driver_sql("ALTER TABLE users ADD COLUMN password_hash TEXT")
            conn.commit()
        except Exception:
            pass


def _ensure_user_profile_columns() -> None:
    """Migrate user_profiles table to use aligned field names."""
    if not settings.DATABASE_URL.startswith("sqlite"):
        return
    with engine.connect() as conn:
        try:
            result = conn.exec_driver_sql("PRAGMA table_info(user_profiles)")
            existing = {row[1] for row in result.fetchall()}
            # Add new aligned columns (old ones remain for any existing rows)
            for col in ["platforms", "genres", "fav_movies", "fav_actors", "fav_directors"]:
                if col not in existing:
                    conn.exec_driver_sql(f"ALTER TABLE user_profiles ADD COLUMN {col} JSON")
            conn.commit()
        except Exception:
            pass
