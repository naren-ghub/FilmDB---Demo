"""
FilmDB — Web Scraping & Knowledge Extraction Pipeline
======================================================
Scrapes film analysis articles from curated sources, extracts entities,
maps to IMDb IDs, chunks for RAG, and stores as JSONL.

Usage:
    python scripts/scraping_pipeline.py --sources bfi senses_of_cinema --max-articles 10
    python scripts/scraping_pipeline.py --dry-run
    python scripts/scraping_pipeline.py --sources all --max-articles 50
"""

import argparse
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

# ─── Paths ──────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "rag" / "processed_dataset"
OUTPUT_DIR = PROJECT_ROOT / "rag" / "scraped_articles"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = OUTPUT_DIR / "scraped_urls.json"

# ─── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "scraping_pipeline.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("scraping_pipeline")

# ─── Source Configuration ───────────────────────────────────────────────────

SOURCES: dict[str, dict[str, Any]] = {
    "bfi": {
        "name": "BFI (British Film Institute)",
        "seed_urls": [
            "https://www.bfi.org.uk/sight-and-sound",
            "https://www.bfi.org.uk/features",
            "https://www.bfi.org.uk/lists",
        ],
        "domain": "www.bfi.org.uk",
        "knowledge_type": "film_theory",
        "link_patterns": ["/features/", "/sight-and-sound/", "/lists/"],
        "exclude_patterns": ["/events/", "/watch/", "/join/", "/about/", "/education/"],
    },
    "senses_of_cinema": {
        "name": "Senses of Cinema",
        "seed_urls": [
            "https://www.sensesofcinema.com/category/great-directors/",
            "https://www.sensesofcinema.com/category/great-actors/",
            "https://www.sensesofcinema.com/category/feature-articles/",
            "https://www.sensesofcinema.com/category/cteq/",
        ],
        "domain": "www.sensesofcinema.com",
        "knowledge_type": "director_analysis",
        "link_patterns": ["/great-directors/", "/great-actors/", "/feature-articles/", "/cteq/"],
        "exclude_patterns": ["/category/", "/tag/", "/page/", "/author/"],
    },
}

# ─── HTTP Session ───────────────────────────────────────────────────────────

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
})

# ─── State Management ──────────────────────────────────────────────────────


def load_state() -> set[str]:
    """Load previously scraped URLs to enable resume."""
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_state(scraped_urls: set[str]) -> None:
    """Persist scraped URLs for resume support."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(scraped_urls), f, indent=2)


# ─── URL Discovery ─────────────────────────────────────────────────────────


def discover_article_urls(source_key: str, max_urls: int = 200) -> list[str]:
    """
    Crawl seed pages to discover article URLs for a given source.
    Only keeps same-domain links that match link_patterns and don't match exclude_patterns.
    """
    source = SOURCES[source_key]
    domain = source["domain"]
    link_patterns = source.get("link_patterns", [])
    exclude_patterns = source.get("exclude_patterns", [])
    discovered: set[str] = set()

    for seed_url in source["seed_urls"]:
        log.info("  Crawling seed: %s", seed_url)
        try:
            resp = SESSION.get(seed_url, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            log.warning("  Failed to fetch seed %s: %s", seed_url, e)
            continue

        soup = BeautifulSoup(resp.text, "html.parser")

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]

            # Resolve relative URLs
            if href.startswith("/"):
                href = urljoin(seed_url, href)

            # Must be same domain
            parsed = urlparse(href)
            if parsed.netloc and parsed.netloc != domain:
                continue

            # Must not be in exclude patterns
            if any(exc in href for exc in exclude_patterns):
                continue

            # Must match at least one link pattern (if patterns defined)
            if link_patterns and not any(pat in href for pat in link_patterns):
                continue

            # Must look like an article (has a path deeper than just /category/)
            path = parsed.path.rstrip("/")
            if path.count("/") < 2:
                continue

            # Skip pagination, tags, media
            if any(skip in href for skip in ["/page/", "/tag/", ".jpg", ".png", ".pdf", "#"]):
                continue

            discovered.add(href)

        time.sleep(1)  # Polite crawling delay

    urls = sorted(discovered)[:max_urls]
    log.info("  Discovered %d article URLs for %s", len(urls), source_key)
    return urls


# ─── Article Extraction ────────────────────────────────────────────────────


def extract_article(url: str) -> dict[str, Any] | None:
    """
    Download and extract article content using trafilatura.
    Returns dict with text, title, author, date, or None on failure.
    """
    import trafilatura

    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            log.debug("  trafilatura: no content at %s", url)
            return None

        text = trafilatura.extract(downloaded, include_comments=False)
        if not text:
            return None

        # Extract metadata using JSON output format
        meta_json = trafilatura.extract(
            downloaded,
            output_format="json",
            include_comments=False,
        )
        meta_dict = json.loads(meta_json) if meta_json else {}

        return {
            "text": text,
            "title": meta_dict.get("title"),
            "author": meta_dict.get("author"),
            "date": meta_dict.get("date"),
            "hostname": meta_dict.get("hostname"),
        }
    except Exception as e:
        log.warning("  Extraction failed for %s: %s", url, e)
        return None


# ─── Content Cleaning ──────────────────────────────────────────────────────


def clean_text(text: str) -> str | None:
    """
    Clean extracted article text.
    Returns None if text is too short after cleaning.
    """
    # Remove navigation text patterns
    nav_phrases = [
        r"skip to (?:main )?content",
        r"cookie (?:policy|consent|settings)",
        r"sign up for (?:our )?newsletter",
        r"subscribe (?:to|now)",
        r"all rights reserved",
        r"©\s*\d{4}",
        r"terms (?:of use|and conditions)",
        r"privacy policy",
        r"follow us on",
        r"share (?:this|on)",
    ]
    for pattern in nav_phrases:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # Reject too-short articles (likely nav pages or error pages)
    if len(text) < 400:
        return None

    return text


# ─── Entity Detection ──────────────────────────────────────────────────────

_NLP = None


def _get_nlp():
    """Lazy-load spaCy model."""
    global _NLP
    if _NLP is None:
        import spacy
        _NLP = spacy.load("en_core_web_sm")
    return _NLP


def detect_entities(text: str) -> dict[str, list[str]]:
    """
    Use spaCy NER to extract people and film titles from text.
    """
    nlp = _get_nlp()
    # Process only first 100k chars to avoid memory issues on very long texts
    doc = nlp(text[:100_000])

    people: set[str] = set()
    films: set[str] = set()

    for ent in doc.ents:
        if ent.label_ == "PERSON":
            name = ent.text.strip()
            # Filter out very short or single-char names
            if len(name) > 2 and " " in name:
                people.add(name)
        elif ent.label_ == "WORK_OF_ART":
            title = ent.text.strip()
            if len(title) > 2:
                films.add(title)

    return {
        "directors": sorted(people),  # We can't distinguish role at NER level
        "actors": [],  # Populated later via IMDb mapping
        "films": sorted(films),
    }


# ─── Canonical IMDb Mapping ────────────────────────────────────────────────

_MOVIE_ENTITY: pd.DataFrame | None = None
_TITLE_INDEX: dict[str, str] | None = None  # title_lower → imdb_id


def _load_movie_entity() -> pd.DataFrame | None:
    """Load movie_entity.parquet for IMDb ID matching."""
    global _MOVIE_ENTITY, _TITLE_INDEX
    if _MOVIE_ENTITY is None:
        path = DATA_DIR / "movie_entity.parquet"
        if path.exists():
            _MOVIE_ENTITY = pd.read_parquet(path)
            # Build title → imdb_id index (first occurrence wins)
            titles = _MOVIE_ENTITY["title"].astype(str).str.lower().str.strip()
            ids = _MOVIE_ENTITY["imdb_id"]
            _TITLE_INDEX = {}
            for t, iid in zip(titles, ids):
                if t not in _TITLE_INDEX:
                    _TITLE_INDEX[t] = iid
            log.info("Loaded movie_entity: %d rows, %d unique titles", len(_MOVIE_ENTITY), len(_TITLE_INDEX))
        else:
            log.warning("movie_entity.parquet not found — IMDb mapping disabled")
    return _MOVIE_ENTITY


def map_to_imdb(film_titles: list[str]) -> list[str]:
    """
    Match detected film titles to IMDb IDs using exact → fuzzy matching.
    Returns list of matched IMDb tconst IDs.
    """
    _load_movie_entity()
    if _TITLE_INDEX is None or not film_titles:
        return []

    matched: set[str] = set()

    for film in film_titles:
        ft = film.lower().strip()

        # 1. Exact match
        if ft in _TITLE_INDEX:
            matched.add(_TITLE_INDEX[ft])
            continue

        # 2. Fuzzy match (≥90%) using rapidfuzz extractOne for speed
        try:
            from rapidfuzz import fuzz, process as rfprocess

            result = rfprocess.extractOne(
                ft, _TITLE_INDEX.keys(), scorer=fuzz.ratio, score_cutoff=90
            )
            if result:
                matched.add(_TITLE_INDEX[result[0]])
        except ImportError:
            log.warning("rapidfuzz not installed — fuzzy matching disabled")
            break

    return sorted(matched)


# ─── RAG Chunking ──────────────────────────────────────────────────────────


def chunk_text(text: str, chunk_size: int = 1000, chunk_overlap: int = 150) -> list[str]:
    """
    Split article text into chunks suitable for RAG retrieval.
    Target: 400-600 tokens per chunk (roughly 1000 characters).
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_text(text)


# ─── JSONL Writer ───────────────────────────────────────────────────────────


def save_record(record: dict, output_path: Path) -> None:
    """Append a single record to the JSONL output file."""
    with open(output_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ─── Article Processing Pipeline ───────────────────────────────────────────


def process_article(
    url: str,
    source_key: str,
    dry_run: bool = False,
) -> dict[str, Any] | None:
    """
    Full processing pipeline for a single article URL.
    Returns the processed record dict, or None if the article was skipped.
    """
    source = SOURCES[source_key]

    # 1. Extract article
    extracted = extract_article(url)
    if not extracted or not extracted.get("text"):
        log.debug("  Skip (no content): %s", url)
        return None

    # 2. Clean text
    cleaned = clean_text(extracted["text"])
    if not cleaned:
        log.debug("  Skip (too short): %s", url)
        return None

    # 3. Detect entities
    entities = detect_entities(cleaned)

    # 4. Map films to IMDb IDs
    imdb_ids = map_to_imdb(entities.get("films", []))

    # 5. Chunk for RAG
    chunks = chunk_text(cleaned)

    # 6. Build record
    record = {
        "source": source["name"],
        "knowledge_type": source["knowledge_type"],
        "title": extracted.get("title"),
        "author": extracted.get("author"),
        "publication_date": extracted.get("date"),
        "entities": entities,
        "imdb_ids": imdb_ids,
        "text": cleaned,
        "chunks": chunks,
        "url": url,
    }

    if dry_run:
        log.info(
            "  [DRY-RUN] %s | entities: %d people, %d films | imdb_ids: %d | chunks: %d",
            (extracted.get("title") or "untitled")[:50],
            len(entities.get("directors", [])),
            len(entities.get("films", [])),
            len(imdb_ids),
            len(chunks),
        )
    else:
        log.info(
            "  ✅ %s | chunks: %d | imdb_ids: %d",
            (extracted.get("title") or "untitled")[:50],
            len(chunks),
            len(imdb_ids),
        )

    return record


# ─── Main Pipeline ─────────────────────────────────────────────────────────


def run_pipeline(
    source_keys: list[str],
    max_articles: int = 50,
    output_path: Path | None = None,
    dry_run: bool = False,
    workers: int = 5,
) -> None:
    """
    Execute the full scraping pipeline for the given sources.
    """
    if output_path is None:
        output_path = OUTPUT_DIR / "analysis_layer.jsonl"

    scraped_urls = load_state()
    total_new = 0
    total_skipped = 0

    for source_key in source_keys:
        if source_key not in SOURCES:
            log.warning("Unknown source: %s — skipping", source_key)
            continue

        log.info("═══ Processing source: %s ═══", SOURCES[source_key]["name"])

        # 1. Discover URLs
        all_urls = discover_article_urls(source_key, max_urls=max_articles * 3)

        # 2. Filter already-scraped URLs
        new_urls = [u for u in all_urls if u not in scraped_urls]
        new_urls = new_urls[:max_articles]

        if not new_urls:
            log.info("  No new URLs to process for %s", source_key)
            continue

        log.info("  Processing %d new articles (skipping %d already done)",
                 len(new_urls), len(all_urls) - len(new_urls))

        # 3. Process articles (with thread pool for I/O-bound downloads)
        records: list[dict] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_url = {
                executor.submit(process_article, url, source_key, dry_run): url
                for url in new_urls
            }

            for future in tqdm(
                as_completed(future_to_url),
                total=len(future_to_url),
                desc=f"  {source_key}",
                unit="article",
            ):
                url = future_to_url[future]
                try:
                    result = future.result()
                    if result:
                        records.append(result)
                        scraped_urls.add(url)
                    else:
                        total_skipped += 1
                except Exception as e:
                    import traceback
                    log.error("  Error processing %s: %s\n%s", url, e, traceback.format_exc())
                    total_skipped += 1

        # 4. Save records
        if not dry_run:
            for record in records:
                save_record(record, output_path)

        total_new += len(records)
        log.info("  Source %s: %d articles saved", source_key, len(records))

    # 5. Save state
    save_state(scraped_urls)

    log.info("═══ Pipeline complete ═══")
    log.info("  New articles: %d", total_new)
    log.info("  Skipped: %d", total_skipped)
    log.info("  Total scraped URLs: %d", len(scraped_urls))
    if not dry_run:
        log.info("  Output: %s", output_path)


# ─── CLI ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="FilmDB Web Scraping Pipeline — scrape film analysis articles",
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        default=["all"],
        help="Source keys to scrape (e.g. bfi senses_of_cinema) or 'all'",
    )
    parser.add_argument(
        "--max-articles",
        type=int,
        default=50,
        help="Maximum articles per source (default: 50)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSONL file path (default: rag/scraped_articles/analysis_layer.jsonl)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run pipeline without writing output (for testing)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Number of parallel download workers (default: 5)",
    )

    args = parser.parse_args()

    # Resolve source keys
    if "all" in args.sources:
        source_keys = list(SOURCES.keys())
    else:
        source_keys = args.sources

    # Resolve output path
    output_path = Path(args.output) if args.output else None

    log.info("Starting FilmDB scraping pipeline")
    log.info("  Sources: %s", source_keys)
    log.info("  Max articles/source: %d", args.max_articles)
    log.info("  Dry run: %s", args.dry_run)
    log.info("  Workers: %d", args.workers)

    run_pipeline(
        source_keys=source_keys,
        max_articles=args.max_articles,
        output_path=output_path,
        dry_run=args.dry_run,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
