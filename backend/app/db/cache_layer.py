from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy.orm import Session

from app.db.models import MovieMetadataCache, SimilarityCache, StreamingCache


def _is_fresh(cached_at: datetime, max_age_hours: int) -> bool:
    return datetime.utcnow() - cached_at < timedelta(hours=max_age_hours)


def get_metadata_cache(
    db: Session, title: str, max_age_hours: int = 24
) -> MovieMetadataCache | None:
    row = db.query(MovieMetadataCache).filter(MovieMetadataCache.title == title).first()
    if not row:
        return None
    if not _is_fresh(cast(datetime, row.cached_at), max_age_hours):
        return None
    return row


def set_metadata_cache(
    db: Session, title: str, imdb_data: dict, wikipedia_data: dict
) -> MovieMetadataCache:
    row = db.query(MovieMetadataCache).filter(MovieMetadataCache.title == title).first()
    if not row:
        row = MovieMetadataCache(title=title, imdb_data=imdb_data, wikipedia_data=wikipedia_data)
        db.add(row)
    else:
        cast(Any, row).imdb_data = imdb_data
        cast(Any, row).wikipedia_data = wikipedia_data
        cast(Any, row).cached_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def get_streaming_cache(
    db: Session, title: str, region: str, max_age_hours: int = 24
) -> StreamingCache | None:
    row = (
        db.query(StreamingCache)
        .filter(StreamingCache.title == title, StreamingCache.region == region)
        .first()
    )
    if not row:
        return None
    if not _is_fresh(cast(datetime, row.cached_at), max_age_hours):
        return None
    return row


def set_streaming_cache(
    db: Session, title: str, region: str, streaming_data: dict
) -> StreamingCache:
    row = (
        db.query(StreamingCache)
        .filter(StreamingCache.title == title, StreamingCache.region == region)
        .first()
    )
    if not row:
        row = StreamingCache(title=title, region=region, streaming_data=streaming_data)
        db.add(row)
    else:
        cast(Any, row).streaming_data = streaming_data
        cast(Any, row).cached_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def get_similarity_cache(
    db: Session, title: str, max_age_hours: int = 24 * 30
) -> SimilarityCache | None:
    row = db.query(SimilarityCache).filter(SimilarityCache.title == title).first()
    if not row:
        return None
    if not _is_fresh(cast(datetime, row.cached_at), max_age_hours):
        return None
    return row


def set_similarity_cache(db: Session, title: str, recommendations: dict) -> SimilarityCache:
    row = db.query(SimilarityCache).filter(SimilarityCache.title == title).first()
    if not row:
        row = SimilarityCache(title=title, recommendations=recommendations)
        db.add(row)
    else:
        cast(Any, row).recommendations = recommendations
        cast(Any, row).cached_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row
