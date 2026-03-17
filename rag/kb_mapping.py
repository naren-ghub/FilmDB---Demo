"""
FilmDB — Knowledge Base Mapping Pipeline
==========================================
Builds 7 canonical Parquet layers from raw datasets using IMDb ID (tconst) as
the global primary identifier.

Output layers:
    1.  movie_entity.parquet        — Master movie table (IMDb core)
    1.5 person_index.parquet        — Pre-aggregated person filmography index
    2.  metadata_layer.parquet      — TMDB enrichment (overview, popularity…)
    3.  plot_layer.parquet          — Wikipedia plot summaries

    5.  recommendation_layer.parquet — MovieLens aggregated ratings/tags
    6.  regional_layer.parquet      — Indian cinema regional data

Future layer (placeholder):
    7.  analysis_layer.jsonl        — Scraped web articles (BFI, Film Companion…)

Usage:
    python rag/kb_mapping.py              # run full pipeline
    python rag/kb_mapping.py --layer 1    # run only a specific layer
    python rag/kb_mapping.py --layer 1.5  # build person index only
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import pandas as pd
from tqdm import tqdm

# ─── Paths ──────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "rag" / "raw_dataset"
OUT_DIR = PROJECT_ROOT / "rag" / "processed_dataset"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Source paths
IMDB_DIR = RAW_DIR / "IMDb"
GROUPLENS_DIR = RAW_DIR / "grouplens" / "ml-32m"
INDIAN_DIR = RAW_DIR / "indian movies"
RT_DIR = RAW_DIR / "rotten_tomato_film_review"
TMDB_DIR = RAW_DIR / "the_movie_data_set_tmdb"
WIKI_DIR = RAW_DIR / "wikipedia_movie_plot"

# ─── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("kb_mapping")


# ─── Helpers ────────────────────────────────────────────────────────────────

def _save_parquet(df: pd.DataFrame, name: str) -> None:
    """Save a DataFrame to Parquet and log stats."""
    path = OUT_DIR / name
    df.to_parquet(path, index=False, engine="pyarrow")
    size_mb = path.stat().st_size / (1024 * 1024)
    log.info(f"  ✅ Saved {name}: {len(df):,} rows, {size_mb:.1f} MB")


def _normalize_imdb_id(raw: str) -> str:
    """Ensure consistent tt-prefixed 9-char IMDb ID format."""
    s = str(raw).strip()
    if s.startswith("tt"):
        return s
    return "tt" + s.zfill(7)


def _clean_null(val):
    """Replace IMDb \\N sentinel with None/NaN."""
    if isinstance(val, str) and val in ("\\N", "\\\\N", ""):
        return None
    return val


# ─── Layer 1: movie_entity ──────────────────────────────────────────────────

def build_movie_entity() -> pd.DataFrame:
    """
    Build the canonical movie master table from IMDb title.basics.tsv.
    Enriches with tmdb_id and movielens_id via cross-reference tables.
    """
    log.info("═══ Layer 1: movie_entity (IMDb master) ═══")
    start = time.monotonic()

    # ── Load IMDb title.basics ─────────────────────────────────────────────
    basics_path = IMDB_DIR / "title.basics.tsv" / "title.basics.tsv"
    log.info(f"  Loading {basics_path.name} …")

    basics = pd.read_csv(
        basics_path,
        sep="\t",
        dtype=str,
        na_values="\\N",
        low_memory=False,
        usecols=["tconst", "titleType", "primaryTitle", "startYear",
                 "runtimeMinutes", "genres", "isAdult"],
    )
    log.info(f"  Loaded {len(basics):,} total title rows")

    # Filter to movies only (exclude shorts, TV, etc.) and non-adult
    movies = basics[
        (basics["titleType"] == "movie") &
        (basics["isAdult"] != "1")
    ].copy()
    movies = movies.drop(columns=["titleType", "isAdult"])
    movies = movies.rename(columns={
        "tconst": "imdb_id",
        "primaryTitle": "title",
        "startYear": "year",
        "runtimeMinutes": "runtime",
    })
    log.info(f"  Filtered to {len(movies):,} movies (non-adult)")

    # ── Add IMDb ratings ───────────────────────────────────────────────────
    ratings_path = IMDB_DIR / "title.ratings.tsv" / "title.ratings.tsv"
    if ratings_path.exists():
        log.info(f"  Merging IMDb ratings …")
        ratings = pd.read_csv(
            ratings_path, sep="\t", dtype=str, na_values="\\N",
        )
        ratings = ratings.rename(columns={
            "tconst": "imdb_id",
            "averageRating": "imdb_rating",
            "numVotes": "imdb_votes",
        })
        movies = movies.merge(ratings, on="imdb_id", how="left")
        log.info(f"  Ratings merged: {movies['imdb_rating'].notna().sum():,} rated movies")

    # ── Cross-reference: TMDB ID ───────────────────────────────────────────
    tmdb_v11_path = TMDB_DIR / "TMDB_movie_dataset_v11.csv"
    if tmdb_v11_path.exists():
        log.info(f"  Cross-referencing TMDB IDs …")
        # Only load the two columns we need to keep memory low
        tmdb_ids = pd.read_csv(
            tmdb_v11_path,
            usecols=["id", "imdb_id"],
            dtype=str,
            low_memory=False,
        )
        tmdb_ids = tmdb_ids.dropna(subset=["imdb_id"])
        tmdb_ids = tmdb_ids.drop_duplicates(subset=["imdb_id"])
        tmdb_ids = tmdb_ids.rename(columns={"id": "tmdb_id", "imdb_id": "imdb_id"})
        movies = movies.merge(tmdb_ids, on="imdb_id", how="left")
        matched = movies["tmdb_id"].notna().sum()
        log.info(f"  TMDB IDs matched: {matched:,}")
    else:
        movies["tmdb_id"] = None

    # ── Cross-reference: MovieLens ID ──────────────────────────────────────
    gl_links_path = GROUPLENS_DIR / "links.csv"
    if gl_links_path.exists():
        log.info(f"  Cross-referencing MovieLens IDs …")
        gl_links = pd.read_csv(gl_links_path, dtype=str)
        gl_links["imdb_id"] = "tt" + gl_links["imdbId"].str.zfill(7)
        gl_links = gl_links.rename(columns={"movieId": "movielens_id"})
        gl_links = gl_links[["imdb_id", "movielens_id"]].drop_duplicates(subset=["imdb_id"])
        movies = movies.merge(gl_links, on="imdb_id", how="left")
        matched = movies["movielens_id"].notna().sum()
        log.info(f"  MovieLens IDs matched: {matched:,}")
    else:
        movies["movielens_id"] = None

    # ── Cross-reference: Regional Data (Indian Movies) ────────────────────
    indian_path = INDIAN_DIR / "indian movies.csv"
    if indian_path.exists():
        log.info(f"  Merging Regional data (language, region) …")
        indian = pd.read_csv(
            indian_path, dtype=str, low_memory=False, usecols=["ID", "Language"]
        )
        indian = indian.rename(columns={"ID": "imdb_id", "Language": "language"})
        indian["region"] = "India"
        
        # Drop duplicates before merging
        indian = indian.dropna(subset=["imdb_id"]).drop_duplicates(subset=["imdb_id"])
        
        movies = movies.merge(indian, on="imdb_id", how="left")
        log.info(f"  Regional language matched: {movies['language'].notna().sum():,}")
    else:
        movies["language"] = None
        movies["region"] = None

    # ── Save ───────────────────────────────────────────────────────────────
    _save_parquet(movies, "movie_entity.parquet")
    elapsed = time.monotonic() - start
    log.info(f"  Layer 1 done in {elapsed:.1f}s\n")
    return movies


# ─── Layer 2: metadata_layer (TMDB enrichment) ──────────────────────────────

def build_metadata_layer(movie_entity: pd.DataFrame) -> pd.DataFrame:
    """
    Enrich movies with TMDB metadata: overview, popularity, tagline, budget, etc.
    """
    log.info("═══ Layer 2: metadata_layer (TMDB enrichment) ═══")
    start = time.monotonic()

    tmdb_path = TMDB_DIR / "TMDB_movie_dataset_v11.csv"
    log.info(f"  Loading TMDB v11 dataset …")

    tmdb = pd.read_csv(
        tmdb_path,
        dtype=str,
        low_memory=False,
        usecols=[
            "id", "imdb_id", "title", "overview", "popularity",
            "vote_average", "vote_count", "tagline", "budget",
            "revenue", "poster_path", "keywords",
            "production_companies", "spoken_languages",
            "original_language", "release_date", "status",
        ],
    )
    tmdb = tmdb.dropna(subset=["imdb_id"])
    tmdb = tmdb.drop_duplicates(subset=["imdb_id"])
    log.info(f"  TMDB rows with imdb_id: {len(tmdb):,}")

    # Keep only movies that exist in our master table
    valid_ids = set(movie_entity["imdb_id"])
    tmdb = tmdb[tmdb["imdb_id"].isin(valid_ids)].copy()
    log.info(f"  Matched to movie_entity: {len(tmdb):,}")

    # Rename for clarity
    tmdb = tmdb.rename(columns={"id": "tmdb_id"})

    _save_parquet(tmdb, "metadata_layer.parquet")
    elapsed = time.monotonic() - start
    log.info(f"  Layer 2 done in {elapsed:.1f}s\n")
    return tmdb


# ─── Layer 3: plot_layer (Wikipedia) ────────────────────────────────────────

def build_plot_layer(movie_entity: pd.DataFrame) -> pd.DataFrame:
    """
    Map Wikipedia movie plots to IMDb IDs using title+year fuzzy matching.
    """
    log.info("═══ Layer 3: plot_layer (Wikipedia plots) ═══")
    start = time.monotonic()

    wiki_path = WIKI_DIR / "wiki_movie_plots_deduped.csv"
    log.info(f"  Loading Wikipedia plots …")

    wiki = pd.read_csv(wiki_path, dtype=str, low_memory=False)
    wiki = wiki.rename(columns={
        "Release Year": "year",
        "Title": "title",
        "Origin/Ethnicity": "origin_ethnicity",
        "Director": "director",
        "Cast": "cast",
        "Genre": "genre",
        "Wiki Page": "wiki_page",
        "Plot": "plot_text",
    })
    wiki = wiki.dropna(subset=["title", "plot_text"])
    log.info(f"  Wiki rows with title+plot: {len(wiki):,}")

    # Build lookup from movie_entity: normalized title+year → imdb_id
    log.info(f"  Building title+year lookup index …")
    me = movie_entity[["imdb_id", "title", "year"]].dropna(subset=["title"]).copy()
    me["_lookup"] = me["title"].str.lower().str.strip() + "|" + me["year"].fillna("").astype(str)
    lookup_dict = dict(zip(me["_lookup"], me["imdb_id"]))

    # Also build a title-only lookup for cases where year is missing or mismatched
    title_only_dict: dict[str, str] = {}
    for _, row in me.iterrows():
        t = str(row["title"]).lower().strip()
        if t not in title_only_dict:
            title_only_dict[t] = row["imdb_id"]

    # Match wiki plots
    log.info(f"  Matching wiki plots to IMDb IDs …")
    matched_ids = []
    for _, row in tqdm(wiki.iterrows(), total=len(wiki), desc="  Wiki→IMDb"):
        title_norm = str(row["title"]).lower().strip()
        year_str = str(row.get("year", "")).strip()
        key = title_norm + "|" + year_str

        imdb_id = lookup_dict.get(key)
        if not imdb_id:
            # Try title-only fallback
            imdb_id = title_only_dict.get(title_norm)
        matched_ids.append(imdb_id)

    wiki["imdb_id"] = matched_ids
    wiki["source"] = "Wikipedia"

    matched = wiki["imdb_id"].notna().sum()
    log.info(f"  Matched: {matched:,} / {len(wiki):,} ({matched/len(wiki)*100:.1f}%)")

    # Keep only matched rows
    plot_layer = wiki[wiki["imdb_id"].notna()][[
        "imdb_id", "plot_text", "source", "origin_ethnicity",
        "director", "cast", "genre", "wiki_page",
    ]].copy()

    _save_parquet(plot_layer, "plot_layer.parquet")
    elapsed = time.monotonic() - start
    log.info(f"  Layer 3 done in {elapsed:.1f}s\n")
    return plot_layer




# ─── Layer 5: recommendation_layer (MovieLens) ──────────────────────────────

def build_recommendation_layer(movie_entity: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate MovieLens ratings and tags per movie, keyed by imdb_id.
    Note: We aggregate 32M ratings down to per-movie stats, not individual rows.
    """
    log.info("═══ Layer 5: recommendation_layer (MovieLens ML-32M) ═══")
    start = time.monotonic()

    # ── Build movielens_id → imdb_id lookup ────────────────────────────────
    links_path = GROUPLENS_DIR / "links.csv"
    links = pd.read_csv(links_path, dtype=str)
    links["imdb_id"] = "tt" + links["imdbId"].str.zfill(7)
    ml_to_imdb = dict(zip(links["movieId"], links["imdb_id"]))
    log.info(f"  MovieLens link entries: {len(links):,}")

    # ── Aggregate ratings (chunked) ────────────────────────────────────────
    ratings_path = GROUPLENS_DIR / "ratings.csv"
    log.info(f"  Aggregating MovieLens ratings (chunked, 32M rows) …")

    rating_aggs: dict[str, list[float]] = {}
    chunk_count = 0
    for chunk in pd.read_csv(
        ratings_path,
        dtype={"userId": str, "movieId": str, "rating": float, "timestamp": str},
        usecols=["movieId", "rating"],
        chunksize=500_000,
    ):
        for movie_id, rating in zip(chunk["movieId"], chunk["rating"]):
            imdb_id = ml_to_imdb.get(movie_id)
            if imdb_id:
                if imdb_id not in rating_aggs:
                    rating_aggs[imdb_id] = []
                rating_aggs[imdb_id].append(rating)
        chunk_count += 1
        if chunk_count % 10 == 0:
            log.info(f"    Processed {chunk_count * 500_000:,} rating rows …")

    log.info(f"  Computing per-movie stats for {len(rating_aggs):,} movies …")
    rating_records = []
    for imdb_id, ratings in rating_aggs.items():
        rating_records.append({
            "imdb_id": imdb_id,
            "ml_avg_rating": round(sum(ratings) / len(ratings), 3),
            "ml_rating_count": len(ratings),
        })
    ratings_df = pd.DataFrame(rating_records)

    # ── Aggregate tags (chunked) ───────────────────────────────────────────
    tags_path = GROUPLENS_DIR / "tags.csv"
    log.info(f"  Aggregating MovieLens tags …")

    tag_aggs: dict[str, list[str]] = {}
    for chunk in pd.read_csv(
        tags_path,
        dtype=str,
        usecols=["movieId", "tag"],
        chunksize=200_000,
    ):
        chunk = chunk.dropna(subset=["tag"])
        for movie_id, tag in zip(chunk["movieId"], chunk["tag"]):
            imdb_id = ml_to_imdb.get(movie_id)
            if imdb_id:
                if imdb_id not in tag_aggs:
                    tag_aggs[imdb_id] = []
                tag_aggs[imdb_id].append(str(tag).strip())

    # Deduplicate and join top-N tags
    log.info(f"  Computing top tags for {len(tag_aggs):,} movies …")
    tag_records = []
    for imdb_id, tags in tag_aggs.items():
        # Count tag frequency and keep top 20
        from collections import Counter
        top_tags = [tag for tag, _ in Counter(tags).most_common(20)]
        tag_records.append({
            "imdb_id": imdb_id,
            "ml_tags": "|".join(top_tags),
            "ml_tag_count": len(tags),
        })
    tags_df = pd.DataFrame(tag_records)

    # ── Merge ratings + tags ───────────────────────────────────────────────
    rec_layer = ratings_df.merge(tags_df, on="imdb_id", how="outer")

    # Add movielens_id back
    imdb_to_ml = {v: k for k, v in ml_to_imdb.items()}
    rec_layer["movielens_id"] = rec_layer["imdb_id"].map(imdb_to_ml)
    
    # ── E.5: Enrich with TMDB Keywords ──────────────
    log.info(f"  Enriching tags with TMDB keywords from metadata_layer …")
    metadata_path = OUT_DIR / "metadata_layer.parquet"
    if metadata_path.exists():
        metadata_df = pd.read_parquet(metadata_path, columns=["imdb_id", "keywords"])
        rec_layer = rec_layer.merge(metadata_df, on="imdb_id", how="left")
        
        # Merge MovieLens tags and TMDB keywords
        def merge_tags(row):
            ml_tag_list = str(row.get("ml_tags", "")).split("|") if pd.notna(row.get("ml_tags")) else []
            tmdb_keywords = str(row.get("keywords", "")).split("|") if pd.notna(row.get("keywords")) else []
            
            combined = set()
            for t in ml_tag_list + tmdb_keywords:
                t = t.strip()
                if t and t.lower() != "nan":
                    combined.add(t)
            
            return "|".join(combined) if combined else None
            
        rec_layer["ml_tags"] = rec_layer.apply(merge_tags, axis=1)
        rec_layer = rec_layer.drop(columns=["keywords"])
    else:
        log.warning("  metadata_layer missing, skipping TMDB keyword enrichment.")

    _save_parquet(rec_layer, "recommendation_layer.parquet")
    elapsed = time.monotonic() - start
    log.info(f"  Layer 5 done in {elapsed:.1f}s\n")
    return rec_layer


# ─── Layer 6: regional_layer (Indian Movies) ────────────────────────────────

def build_regional_layer() -> pd.DataFrame:
    """
    Map Indian movies dataset. The 'ID' column already contains IMDb tconst IDs.
    """
    log.info("═══ Layer 6: regional_layer (Indian Movies) ═══")
    start = time.monotonic()

    indian_path = INDIAN_DIR / "indian movies.csv"
    log.info(f"  Loading Indian movies …")

    indian = pd.read_csv(indian_path, dtype=str, low_memory=False)
    indian = indian.rename(columns={
        "ID": "imdb_id",
        "Movie Name": "title",
        "Year": "year",
        "Timing(min)": "runtime",
        "Rating(10)": "rating",
        "Votes": "votes",
        "Genre": "genre",
        "Language": "language",
    })

    # Clean sentinel values
    for col in ["runtime", "rating", "votes", "genre"]:
        indian[col] = indian[col].replace("-", None)

    # Clean runtime (remove " min" suffix)
    indian["runtime"] = (
        indian["runtime"]
        .str.replace(r"\s*min\s*$", "", regex=True)
        .str.strip()
    )

    # Clean votes (remove commas)
    indian["votes"] = indian["votes"].str.replace(",", "")

    indian["region"] = "India"
    indian["source"] = "indian_movies_dataset"

    regional = indian[[
        "imdb_id", "title", "year", "language", "region",
        "rating", "votes", "genre", "source",
    ]].copy()

    _save_parquet(regional, "regional_layer.parquet")
    elapsed = time.monotonic() - start
    log.info(f"  Layer 6 done in {elapsed:.1f}s\n")
    return regional


# ─── Layer 1.5: person_index (IMDb People) ──────────────────────────────────

def build_person_index(movie_entity: pd.DataFrame) -> pd.DataFrame:
    """
    Build a pre-aggregated person index from IMDb crew + principals + name data.
    Only includes people with at least 1 movie credit in movie_entity.

    Sources:
        - name.basics.tsv    → person names, professions
        - title.crew.tsv     → directors, writers per movie
        - title.principals.tsv → cast, crew per movie (chunked)

    Output schema:
        nconst, name, professions, birth_year, death_year,
        filmography (JSON list of {imdb_id, category, characters})
    """
    log.info("═══ Layer 1.5: person_index (IMDb People) ═══")
    start = time.monotonic()

    valid_movie_ids = set(movie_entity["imdb_id"])
    log.info(f"  Valid movie IDs: {len(valid_movie_ids):,}")

    # ── Step 1: Collect person→movie credits from title.principals.tsv ─────
    principals_path = IMDB_DIR / "title.principals.tsv" / "title.principals.tsv"
    log.info(f"  Loading title.principals.tsv (chunked, ~98M rows) …")

    # person_credits: nconst → list of {imdb_id, category, characters}
    person_credits: dict[str, list[dict]] = {}
    chunk_count = 0
    for chunk in pd.read_csv(
        principals_path,
        sep="\t",
        dtype=str,
        na_values="\\N",
        usecols=["tconst", "nconst", "category", "characters"],
        chunksize=1_000_000,
    ):
        # Filter to only movies in our master table
        chunk = chunk[chunk["tconst"].isin(valid_movie_ids)]
        for _, row in chunk.iterrows():
            nconst = row["nconst"]
            if nconst is None:
                continue
            if nconst not in person_credits:
                person_credits[nconst] = []
            person_credits[nconst].append({
                "imdb_id": row["tconst"],
                "category": row.get("category"),
                "characters": row.get("characters"),
            })
        chunk_count += 1
        if chunk_count % 20 == 0:
            log.info(f"    Processed {chunk_count}M principal rows, {len(person_credits):,} people so far …")

    log.info(f"  Principals done: {len(person_credits):,} people with movie credits")

    # ── Step 2: Supplement with directors/writers from title.crew.tsv ───────
    crew_path = IMDB_DIR / "title.crew.tsv" / "title.crew.tsv"
    if crew_path.exists():
        log.info(f"  Loading title.crew.tsv for director/writer credits …")
        crew = pd.read_csv(
            crew_path,
            sep="\t",
            dtype=str,
            na_values="\\N",
            usecols=["tconst", "directors", "writers"],
        )
        crew = crew[crew["tconst"].isin(valid_movie_ids)]

        for _, row in crew.iterrows():
            tconst = row["tconst"]
            for role, col in [("director", "directors"), ("writer", "writers")]:
                val = row.get(col)
                if not isinstance(val, str):
                    continue
                for nconst in val.split(","):
                    nconst = nconst.strip()
                    if not nconst:
                        continue
                    if nconst not in person_credits:
                        person_credits[nconst] = []
                    # Avoid duplicate entries
                    existing = {(c["imdb_id"], c["category"]) for c in person_credits[nconst]}
                    if (tconst, role) not in existing:
                        person_credits[nconst].append({
                            "imdb_id": tconst,
                            "category": role,
                            "characters": None,
                        })

        log.info(f"  After crew merge: {len(person_credits):,} people")

    # ── Step 3: Load person names from name.basics.tsv ─────────────────────
    names_path = IMDB_DIR / "name.basics.tsv" / "name.basics.tsv"
    log.info(f"  Loading name.basics.tsv for person metadata …")

    names = pd.read_csv(
        names_path,
        sep="\t",
        dtype=str,
        na_values="\\N",
        usecols=["nconst", "primaryName", "primaryProfession", "birthYear", "deathYear"],
    )
    # Filter to only people we have credits for
    relevant_nconsts = set(person_credits.keys())
    names = names[names["nconst"].isin(relevant_nconsts)].copy()
    log.info(f"  Names matched: {len(names):,}")

    # ── Step 4: Build the index ────────────────────────────────────────────
    import json as _json

    log.info(f"  Building person_index records …")
    records = []
    name_lookup = dict(zip(names["nconst"], zip(
        names["primaryName"],
        names["primaryProfession"],
        names["birthYear"],
        names["deathYear"],
    )))

    for nconst, credits in person_credits.items():
        info = name_lookup.get(nconst)
        if not info:
            continue  # Skip people not in name.basics
        name, profession, birth_year, death_year = info
        # De-duplicate credits and limit to avoid huge rows
        unique_credits = {}
        for c in credits:
            key = (c["imdb_id"], c["category"])
            if key not in unique_credits:
                unique_credits[key] = c
        credit_list = list(unique_credits.values())

        records.append({
            "nconst": nconst,
            "name": name,
            "professions": profession,
            "birth_year": birth_year,
            "death_year": death_year,
            "credit_count": len(credit_list),
            "filmography_json": _json.dumps(credit_list, ensure_ascii=False),
        })

    person_index = pd.DataFrame(records)
    log.info(f"  Person index: {len(person_index):,} people")

    _save_parquet(person_index, "person_index.parquet")
    elapsed = time.monotonic() - start
    log.info(f"  Layer 1.5 done in {elapsed:.1f}s\n")
    return person_index


# ─── Layer 7 Placeholder: analysis_layer (Web Scraping) ─────────────────────

def create_analysis_layer_schema() -> None:
    """
    Creates the schema definition and placeholder for the future web-scraped
    film analysis corpus. No data is produced yet — the user will run the
    scraping pipeline separately.
    """
    log.info("═══ Layer 7: analysis_layer (placeholder — awaiting scraping) ═══")

    schema_doc = {
        "_schema_version": "1.0",
        "_description": (
            "Film analysis articles scraped from BFI, Senses of Cinema, "
            "Bright Lights Film Journal, Film Companion, and CineFiles. "
            "Each record is a cleaned article mapped to IMDb IDs."
        ),
        "_status": "awaiting_scraping",
        "expected_fields": {
            "source": "str — e.g. 'BFI', 'Film Companion'",
            "knowledge_type": "str — one of: film_theory, director_analysis, film_analysis, film_review",
            "title": "str — article title",
            "author": "str — article author",
            "publication_date": "str — ISO date",
            "entities": {
                "directors": "list[str]",
                "actors": "list[str]",
                "films": "list[str]",
            },
            "imdb_ids": "list[str] — IMDb tconst IDs matched via fuzzy search",
            "text": "str — cleaned article body text",
            "chunks": "list[str] — text split into 400-600 token segments for RAG",
            "url": "str — source URL",
        },
        "target_sources": [
            {
                "name": "BFI (British Film Institute)",
                "seed_urls": [
                    "https://www.bfi.org.uk/sight-and-sound",
                    "https://www.bfi.org.uk/features",
                ],
                "knowledge_type": "film_theory",
            },
            {
                "name": "Senses of Cinema",
                "seed_urls": [
                    "https://www.sensesofcinema.com/category/great-directors/",
                    "https://www.sensesofcinema.com/category/great-actors/",
                ],
                "knowledge_type": "director_analysis",
            },
            {
                "name": "Bright Lights Film Journal",
                "seed_urls": [
                    "https://brightlightsfilm.com/category/artificial-intelligence-ai/",
                    "https://brightlightsfilm.com/category/directors/",
                ],
                "knowledge_type": "film_analysis",
            },
            {
                "name": "Film Companion",
                "seed_urls": [
                    "https://www.filmcompanion.in/reviews/tamil",
                    "https://www.filmcompanion.in/reviews/hindi",
                    "https://www.filmcompanion.in/reviews/malayalam",
                ],
                "knowledge_type": "film_review",
            },
        ],
    }

    import json
    schema_path = OUT_DIR / "analysis_layer_schema.json"
    with open(schema_path, "w", encoding="utf-8") as f:
        json.dump(schema_doc, f, indent=2, ensure_ascii=False)

    # Create empty JSONL file for future scraping output
    jsonl_path = PROJECT_ROOT / "rag" / "scraped_articles" / "analysis_layer.jsonl"
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    if not jsonl_path.exists():
        jsonl_path.touch()
        log.info(f"  Created empty {jsonl_path.name}")

    log.info(f"  ✅ Schema saved to {schema_path.name}")
    log.info(f"  ⏳ analysis_layer.jsonl awaiting scraping pipeline\n")


# ─── Main Pipeline ──────────────────────────────────────────────────────────

def run_full_pipeline() -> None:
    """Execute all 6+1 layers in sequence."""
    total_start = time.monotonic()
    log.info("╔══════════════════════════════════════════════╗")
    log.info("║   FilmDB Knowledge Base Mapping Pipeline     ║")
    log.info("╚══════════════════════════════════════════════╝\n")

    # Layer 1: Master table
    movie_entity = build_movie_entity()

    # Layer 1.5: Person index
    build_person_index(movie_entity)

    # Layer 2: TMDB metadata
    build_metadata_layer(movie_entity)

    # Layer 3: Wikipedia plots
    build_plot_layer(movie_entity)



    # Layer 5: MovieLens recommendations
    build_recommendation_layer(movie_entity)

    # Layer 6: Indian regional movies
    build_regional_layer()

    # Layer 7: Placeholder for scraped articles
    create_analysis_layer_schema()

    # ── Summary ────────────────────────────────────────────────────────────
    total_elapsed = time.monotonic() - total_start
    log.info("╔══════════════════════════════════════════════╗")
    log.info("║               Pipeline Complete              ║")
    log.info("╚══════════════════════════════════════════════╝")
    log.info(f"  Total time: {total_elapsed/60:.1f} minutes")
    log.info(f"  Output dir: {OUT_DIR}")

    # List output files
    for f in sorted(OUT_DIR.iterdir()):
        size_mb = f.stat().st_size / (1024 * 1024)
        log.info(f"    {f.name}: {size_mb:.1f} MB")


def _load_movie_entity() -> pd.DataFrame:
    """Load existing movie_entity.parquet or build it."""
    me_path = OUT_DIR / "movie_entity.parquet"
    if not me_path.exists():
        log.info("movie_entity.parquet not found, building Layer 1 first …")
        return build_movie_entity()
    log.info("Loading existing movie_entity.parquet …")
    me = pd.read_parquet(me_path)
    log.info(f"  Loaded {len(me):,} movies\n")
    return me


def run_single_layer(layer_num: float) -> None:
    """Execute a single layer by number. Supports 1.5 for person_index."""
    if layer_num == 1:
        build_movie_entity()
    elif layer_num == 1.5:
        movie_entity = _load_movie_entity()
        build_person_index(movie_entity)
    elif layer_num in (2, 3, 4, 5):
        movie_entity = _load_movie_entity()
        if layer_num == 2:
            build_metadata_layer(movie_entity)
        elif layer_num == 3:
            build_plot_layer(movie_entity)

        elif layer_num == 5:
            build_recommendation_layer(movie_entity)
    elif layer_num == 6:
        build_regional_layer()
    elif layer_num == 7:
        create_analysis_layer_schema()
    else:
        log.error(f"Unknown layer number: {layer_num}. Valid: 1, 1.5, 2-7")


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FilmDB Knowledge Base Mapping Pipeline")
    parser.add_argument(
        "--layer", type=float, default=None,
        help="Run a specific layer (1, 1.5, 2-7). Default: run all.",
    )
    args = parser.parse_args()

    if args.layer is not None:
        run_single_layer(args.layer)
    else:
        run_full_pipeline()
