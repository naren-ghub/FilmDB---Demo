"""
FilmDB Query Engine — Data Access Layer
=========================================
Central access point for all Parquet KB layers.
Loaded once at startup, provides typed lookup methods for all tools.

Layers used:
    - movie_entity.parquet        → entity lookup, top rated, resolve title
    - metadata_layer.parquet      → TMDB enrichment (overview, poster, etc.)
    - plot_layer.parquet           → Wikipedia plot text
    - review_layer.parquet         → Rotten Tomatoes critic reviews
    - recommendation_layer.parquet → MovieLens tags/ratings (similarity)
    - regional_layer.parquet       → Indian cinema metadata
    - person_index.parquet         → Person filmography index
    - analysis_layer.jsonl         → Scraped film analysis articles (RAG corpus)
"""

import json
import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd

log = logging.getLogger(__name__)

# ─── Paths ──────────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _PROJECT_ROOT / "rag" / "processed_dataset"


class FilmDBQueryEngine:
    """Singleton-style query engine over 7 Parquet KB layers."""

    _instance: "FilmDBQueryEngine | None" = None

    def __init__(self) -> None:
        log.info("FilmDBQueryEngine: loading Parquet layers …")
        self._movie_entity = self._load("movie_entity.parquet")
        self._metadata = self._load("metadata_layer.parquet")
        self._plots = self._load("plot_layer.parquet")
        self._reviews = self._load("review_layer.parquet")
        self._recommendations = self._load("recommendation_layer.parquet")
        self._regional = self._load("regional_layer.parquet")
        self._persons = self._load("person_index.parquet")

        # ── Load analysis layer (JSONL, not Parquet) ───────────────────────
        self._analysis: list[dict] = []
        _analysis_path = _PROJECT_ROOT / "rag" / "scraped_articles" / "analysis_layer.jsonl"
        if _analysis_path.exists():
            with open(_analysis_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self._analysis.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
            log.info("  Loaded analysis_layer.jsonl: %s records", f"{len(self._analysis):,}")
        else:
            log.info("  analysis_layer.jsonl not found — analysis search disabled")

        # ── Build lookup indices (vectorized for speed) ────────────────────
        self._title_year_index: dict[str, str] = {}
        self._title_index: dict[str, str] = {}

        if self._movie_entity is not None:
            me = self._movie_entity[["imdb_id", "title", "year"]].dropna(subset=["title"])
            titles_lower = me["title"].astype(str).str.lower().str.strip()
            years_str = me["year"].astype(str).where(me["year"].notna(), "").str.strip()
            keys = titles_lower + "|" + years_str
            # Build title+year index (first occurrence wins)
            ty_df = pd.DataFrame({"key": keys, "imdb_id": me["imdb_id"].values})
            ty_df = ty_df.drop_duplicates(subset="key", keep="first")
            self._title_year_index = dict(zip(ty_df["key"], ty_df["imdb_id"]))
            # Build title-only index (first occurrence wins)
            t_df = pd.DataFrame({"title": titles_lower.values, "imdb_id": me["imdb_id"].values})
            t_df = t_df.drop_duplicates(subset="title", keep="first")
            self._title_index = dict(zip(t_df["title"], t_df["imdb_id"]))

        # Person name → nconst index (vectorized)
        self._person_name_index: dict[str, str] = {}
        if self._persons is not None:
            valid = self._persons[self._persons["name"].notna()].copy()
            names_lower = valid["name"].astype(str).str.lower().str.strip()
            self._person_name_index = dict(zip(names_lower, valid["nconst"]))

        log.info(
            "FilmDBQueryEngine: ready — %s movies, %s persons, %s plots, %s reviews, %s analysis",
            f"{len(self._movie_entity):,}" if self._movie_entity is not None else "0",
            f"{len(self._persons):,}" if self._persons is not None else "0",
            f"{len(self._plots):,}" if self._plots is not None else "0",
            f"{len(self._reviews):,}" if self._reviews is not None else "0",
            f"{len(self._analysis):,}",
        )

    @classmethod
    def get_instance(cls) -> "FilmDBQueryEngine":
        """Lazy singleton: load data once, reuse across requests."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _load(filename: str) -> pd.DataFrame | None:
        path = _DATA_DIR / filename
        if not path.exists():
            log.warning("FilmDBQueryEngine: %s not found — skipping", filename)
            return None
        df = pd.read_parquet(path)
        log.info("  Loaded %s: %s rows", filename, f"{len(df):,}")
        return df

    # ─── Title → IMDb ID Resolution ─────────────────────────────────────────

    def resolve_title_to_imdb_id(
        self, title: str, year: Optional[str] = None
    ) -> str | None:
        """
        Resolve a movie title (+ optional year) to an IMDb ID.
        Strategy: exact title+year → exact title → fuzzy match (≥90).
        """
        t = title.lower().strip()

        # 1. Exact title+year
        if year:
            key = f"{t}|{year}"
            hit = self._title_year_index.get(key)
            if hit:
                return hit

        # 2. Exact title only
        hit = self._title_index.get(t)
        if hit:
            return hit

        # 3. Fuzzy match (lazy import to keep startup fast)
        try:
            from rapidfuzz import fuzz, process as rfprocess

            candidates = list(self._title_index.keys())
            if not candidates:
                return None
            match = rfprocess.extractOne(
                t, candidates, scorer=fuzz.ratio, score_cutoff=90
            )
            if match:
                return self._title_index.get(match[0])
        except ImportError:
            log.warning("rapidfuzz not installed — fuzzy matching disabled")

        return None

    # ─── Entity Lookup ───────────────────────────────────────────────────────

    def entity_lookup(self, imdb_id: str) -> dict[str, Any] | None:
        """Full movie entity from movie_entity + metadata_layer."""
        if self._movie_entity is None:
            return None

        row = self._movie_entity[self._movie_entity["imdb_id"] == imdb_id]
        if row.empty:
            return None
        movie = row.iloc[0].to_dict()

        # Enrich with metadata
        if self._metadata is not None:
            meta_row = self._metadata[self._metadata["imdb_id"] == imdb_id]
            if not meta_row.empty:
                meta = meta_row.iloc[0].to_dict()
                movie["overview"] = meta.get("overview")
                movie["popularity"] = meta.get("popularity")
                movie["vote_average"] = meta.get("vote_average")
                movie["vote_count"] = meta.get("vote_count")
                movie["tagline"] = meta.get("tagline")
                movie["poster_path"] = meta.get("poster_path")
                movie["budget"] = meta.get("budget")
                movie["revenue"] = meta.get("revenue")
                movie["keywords"] = meta.get("keywords")
                movie["original_language"] = meta.get("original_language")

        # Enrich with regional data
        if self._regional is not None:
            reg_row = self._regional[self._regional["imdb_id"] == imdb_id]
            if not reg_row.empty:
                reg = reg_row.iloc[0].to_dict()
                movie["language"] = reg.get("language")
                movie["region"] = reg.get("region")

        # Clean NaN values
        return {k: (None if pd.isna(v) else v) for k, v in movie.items()}

    # ─── Plot Analysis ───────────────────────────────────────────────────────

    def plot_analysis(self, imdb_id: str) -> dict[str, Any] | None:
        """Retrieve Wikipedia plot text for a movie."""
        if self._plots is None:
            return None
        row = self._plots[self._plots["imdb_id"] == imdb_id]
        if row.empty:
            return None
        r = row.iloc[0].to_dict()
        return {k: (None if pd.isna(v) else v) for k, v in r.items()}

    # ─── Critic Summary ──────────────────────────────────────────────────────

    def critic_summary(self, imdb_id: str, max_reviews: int = 30) -> dict[str, Any] | None:
        """Aggregate Rotten Tomatoes reviews for a movie."""
        if self._reviews is None:
            return None

        reviews = self._reviews[self._reviews["imdb_id"] == imdb_id]
        if reviews.empty:
            return None

        # Prioritize top critics
        top_reviews = reviews[reviews["is_top_critic"] == "TRUE"]
        other_reviews = reviews[reviews["is_top_critic"] != "TRUE"]
        selected = pd.concat([top_reviews, other_reviews]).head(max_reviews)

        # Compute sentiment breakdown
        sentiments = reviews["sentiment"].value_counts().to_dict()

        review_list = []
        for _, r in selected.iterrows():
            review_list.append({
                "critic_name": r.get("critic_name"),
                "review_text": r.get("review_text"),
                "sentiment": r.get("sentiment"),
                "score": r.get("score"),
                "is_top_critic": r.get("is_top_critic"),
            })

        return {
            "imdb_id": imdb_id,
            "review_count": len(reviews),
            "sentiment_breakdown": sentiments,
            "reviews": review_list,
        }

    # ─── Movie Similarity ────────────────────────────────────────────────────

    def movie_similarity(self, imdb_id: str, top_n: int = 10) -> dict[str, Any] | None:
        """Find similar movies based on shared MovieLens tags."""
        if self._recommendations is None:
            return None

        target_row = self._recommendations[self._recommendations["imdb_id"] == imdb_id]
        if target_row.empty:
            return None

        target_tags_str = target_row.iloc[0].get("ml_tags")
        if not isinstance(target_tags_str, str) or not target_tags_str:
            return None

        target_tags = set(target_tags_str.lower().split("|"))
        if not target_tags:
            return None

        # Score all other movies by tag overlap
        scores = []
        for _, row in self._recommendations.iterrows():
            other_id = row["imdb_id"]
            if other_id == imdb_id:
                continue
            other_tags_str = row.get("ml_tags")
            if not isinstance(other_tags_str, str):
                continue
            other_tags = set(other_tags_str.lower().split("|"))
            overlap = target_tags & other_tags
            if len(overlap) >= 2:
                scores.append({
                    "imdb_id": other_id,
                    "shared_tags": sorted(overlap),
                    "overlap_count": len(overlap),
                    "ml_avg_rating": row.get("ml_avg_rating"),
                })

        # Sort by overlap count (desc), then by rating (desc)
        scores.sort(key=lambda x: (-x["overlap_count"], -(x["ml_avg_rating"] or 0)))
        top_matches = scores[:top_n]

        # Enrich with titles from movie_entity and posters from metadata
        if self._movie_entity is not None:
            me_dict = dict(zip(self._movie_entity["imdb_id"], self._movie_entity["title"]))
            me_year = dict(zip(self._movie_entity["imdb_id"], self._movie_entity["year"]))
            me_genres = dict(zip(self._movie_entity["imdb_id"], self._movie_entity["genres"]))
            
            # Poster mapping
            poster_dict = {}
            if self._metadata is not None:
                poster_dict = dict(zip(self._metadata["imdb_id"], self._metadata["poster_path"]))

            for m in top_matches:
                m["title"] = me_dict.get(m["imdb_id"])
                m["year"] = me_year.get(m["imdb_id"])
                m["genres"] = me_genres.get(m["imdb_id"])
                m["poster_path"] = poster_dict.get(m["imdb_id"])

        return {
            "imdb_id": imdb_id,
            "source_tags": sorted(target_tags),
            "recommendations": top_matches,
        }

    # ─── Top Rated Movies ────────────────────────────────────────────────────

    def top_rated(
        self,
        genre: Optional[str] = None,
        year: Optional[str] = None,
        language: Optional[str] = None,
        count: int = 20,
    ) -> dict[str, Any]:
        """Return top-rated movies from movie_entity, with optional filters."""
        if self._movie_entity is None:
            return {"movies": []}

        df = self._movie_entity.copy()

        # Must have a rating
        df = df[df["imdb_rating"].notna()]

        # Apply filters
        if genre:
            genre_lower = genre.lower()
            df = df[df["genres"].str.lower().str.contains(genre_lower, na=False)]

        if year:
            df = df[df["year"] == str(year)]

        if language and self._regional is not None:
            # Use regional_layer for language filtering
            lang_lower = language.lower()
            regional_ids = self._regional[
                self._regional["language"].str.lower() == lang_lower
            ]["imdb_id"]
            df = df[df["imdb_id"].isin(set(regional_ids))]

        # Sort by rating descending, then by votes descending
        df["_rating_f"] = pd.to_numeric(df["imdb_rating"], errors="coerce")
        df["_votes_f"] = pd.to_numeric(df["imdb_votes"], errors="coerce")
        df = df.sort_values(["_rating_f", "_votes_f"], ascending=[False, False])

        top = df.head(count)
        movies = []
        for _, row in top.iterrows():
            movies.append({
                "imdb_id": row["imdb_id"],
                "title": row["title"],
                "year": row["year"],
                "rating": row["imdb_rating"],
                "votes": row["imdb_votes"],
                "genres": row["genres"],
            })

        return {
            "filters": {"genre": genre, "year": year, "language": language},
            "count": len(movies),
            "movies": movies,
        }

    # ─── Person Filmography ──────────────────────────────────────────────────

    def person_filmography(self, person_name: str) -> dict[str, Any] | None:
        """Lookup person filmography from person_index.parquet."""
        if self._persons is None:
            return None

        name_lower = person_name.lower().strip()

        # 1. Exact match
        nconst = self._person_name_index.get(name_lower)

        # 2. Fuzzy match
        if not nconst:
            try:
                from rapidfuzz import fuzz, process as rfprocess

                candidates = list(self._person_name_index.keys())
                if candidates:
                    match = rfprocess.extractOne(
                        name_lower, candidates, scorer=fuzz.ratio, score_cutoff=85
                    )
                    if match:
                        nconst = self._person_name_index.get(match[0])
            except ImportError:
                pass

        if not nconst:
            return None

        row = self._persons[self._persons["nconst"] == nconst]
        if row.empty:
            return None

        person = row.iloc[0]
        filmography_raw = person.get("filmography_json")
        filmography = json.loads(filmography_raw) if isinstance(filmography_raw, str) else []

        # ── Role priority: primary creative roles first ──────────────────
        _ROLE_PRIORITY = {
            "director": 0, "writer": 1, "producer": 2,
            "actor": 3, "actress": 3, "composer": 4,
            "cinematographer": 4, "editor": 4,
            "self": 5, "archive_footage": 6, "archive_sound": 6,
        }

        # Enrich filmography with titles and ratings
        if self._movie_entity is not None:
            me_dict = dict(zip(self._movie_entity["imdb_id"], self._movie_entity["title"]))
            me_year = dict(zip(self._movie_entity["imdb_id"], self._movie_entity["year"]))
            me_rating = dict(zip(self._movie_entity["imdb_id"], self._movie_entity["imdb_rating"]))
            for entry in filmography:
                iid = entry.get("imdb_id")
                entry["title"] = me_dict.get(iid)
                entry["year"] = me_year.get(iid)
                entry["rating"] = me_rating.get(iid)

        # Deduplicate: keep highest-priority role per imdb_id
        best_per_movie: dict[str, dict] = {}
        for entry in filmography:
            iid = entry.get("imdb_id")
            if not iid:
                continue
            cat = entry.get("category", "unknown")
            priority = _ROLE_PRIORITY.get(cat, 99)
            existing = best_per_movie.get(iid)
            if existing is None or priority < _ROLE_PRIORITY.get(existing.get("category", ""), 99):
                best_per_movie[iid] = entry

        # Sort: role priority first, then year descending
        deduped = list(best_per_movie.values())
        deduped.sort(key=lambda x: (
            _ROLE_PRIORITY.get(x.get("category", ""), 99),
            -(int(x["year"]) if x.get("year") and str(x["year"]).isdigit() else 0),
        ))

        # Group by category for structured output
        grouped: dict[str, list[dict]] = {}
        for entry in deduped:
            cat = entry.get("category", "other")
            grouped.setdefault(cat, []).append(entry)

        return {
            "nconst": nconst,
            "name": person.get("name"),
            "professions": person.get("professions"),
            "birth_year": person.get("birth_year") if pd.notna(person.get("birth_year")) else None,
            "death_year": person.get("death_year") if pd.notna(person.get("death_year")) else None,
            "credit_count": int(person.get("credit_count", 0)),
            "filmography": deduped,
            "filmography_by_role": grouped,
        }

    # ─── Movie Comparison ────────────────────────────────────────────────────

    def compare_movies(
        self, imdb_id_a: str, imdb_id_b: str
    ) -> dict[str, Any] | None:
        """Gather structured data for two movies side-by-side."""
        movie_a = self.entity_lookup(imdb_id_a)
        movie_b = self.entity_lookup(imdb_id_b)

        if not movie_a and not movie_b:
            return None

        result: dict[str, Any] = {}

        if movie_a:
            result["movie_a"] = movie_a
            plot_a = self.plot_analysis(imdb_id_a)
            if plot_a:
                result["movie_a"]["plot_text"] = plot_a.get("plot_text")
            critic_a = self.critic_summary(imdb_id_a, max_reviews=5)
            if critic_a:
                result["movie_a"]["review_summary"] = {
                    "review_count": critic_a["review_count"],
                    "sentiment_breakdown": critic_a["sentiment_breakdown"],
                }
        if movie_b:
            result["movie_b"] = movie_b
            plot_b = self.plot_analysis(imdb_id_b)
            if plot_b:
                result["movie_b"]["plot_text"] = plot_b.get("plot_text")
            critic_b = self.critic_summary(imdb_id_b, max_reviews=5)
            if critic_b:
                result["movie_b"]["review_summary"] = {
                    "review_count": critic_b["review_count"],
                    "sentiment_breakdown": critic_b["sentiment_breakdown"],
                }

        return result

    # ─── Analysis Search ─────────────────────────────────────────────────────

    def analysis_search(self, imdb_id: str, max_results: int = 10) -> list[dict[str, Any]]:
        """Return analysis articles linked to a given IMDb ID."""
        results = []
        for article in self._analysis:
            if imdb_id in article.get("imdb_ids", []):
                results.append({
                    "source": article.get("source"),
                    "knowledge_type": article.get("knowledge_type"),
                    "title": article.get("title"),
                    "author": article.get("author"),
                    "publication_date": article.get("publication_date"),
                    "url": article.get("url"),
                    "chunks": article.get("chunks", []),
                    "text_preview": (article.get("text", "")[:300] + "…")
                                    if article.get("text") else None,
                })
                if len(results) >= max_results:
                    break
        return results

    def analysis_search_by_person(
        self, person_name: str, max_results: int = 10
    ) -> list[dict[str, Any]]:
        """Return analysis articles mentioning a person in detected entities."""
        name_lower = person_name.lower().strip()
        results = []
        for article in self._analysis:
            entities = article.get("entities", {})
            all_people = (
                entities.get("directors", []) + entities.get("actors", [])
            )
            if any(name_lower in p.lower() for p in all_people):
                results.append({
                    "source": article.get("source"),
                    "knowledge_type": article.get("knowledge_type"),
                    "title": article.get("title"),
                    "author": article.get("author"),
                    "url": article.get("url"),
                    "matched_entities": [
                        p for p in all_people if name_lower in p.lower()
                    ],
                    "text_preview": (article.get("text", "")[:300] + "…")
                                    if article.get("text") else None,
                })
                if len(results) >= max_results:
                    break
        return results
