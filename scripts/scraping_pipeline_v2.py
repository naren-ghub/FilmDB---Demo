"""
FilmDB — Entity-Driven Film Essay Crawling Pipeline v2
=======================================================
High-speed cinema analysis dataset builder using entity-driven,
search-based discovery across trusted film journalism domains.

Implements the strategy from film_essay_crawling_strategy_v2.md:
  1. Entity seed list (directors, films, actors)
  2. Domain-restricted trusted sources
  3. Search-based article discovery (DuckDuckGo site: queries)
  4. Parallel article extraction (trafilatura)
  5. Citation expansion (discover new entities from article text)
  6. Auto-curation quality scoring
  7. Canonical IMDb mapping (rapidfuzz)
  8. RAG chunking + JSONL storage

Usage:
    python scripts/scraping_pipeline_v2.py --max-articles 50
    python scripts/scraping_pipeline_v2.py --max-articles 10 --dry-run
    python scripts/scraping_pipeline_v2.py --max-articles 100 --expand-depth 2
"""

import argparse
import hashlib
import json
import logging
import re
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse

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
STATE_FILE = OUTPUT_DIR / "scraped_urls_v2.json"

# ─── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "scraping_pipeline_v2.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("scraping_pipeline_v2")


# ═══════════════════════════════════════════════════════════════════════════
# 1. ENTITY SEED LIST
# ═══════════════════════════════════════════════════════════════════════════

ENTITY_SEEDS: dict[str, list[str]] = {
    "directors": [
        "Charlie Chaplin", "Stanley Kubrick", "Asghar Farhadi",
        "Krzysztof Kieslowski", "Ingmar Bergman", "Satyajit Ray",
        "Charlie Kaufman", "Bharathi Raja", "Akira Kurosawa",
        "Andrei Tarkovsky", "Alfred Hitchcock", "Martin Scorsese",
        "Lars Von Trier", "Mani Ratnam", "Ritwik Ghatak",
        "Abbas Kiarostami", "Federico Fellini", "Christopher Nolan",
        "Coen Brothers", "Michael Haneke",
    ],
    "films": [
        "The Godfather", "Seven Samurai", "Taxi Driver",
        "Lawrence of Arabia", "The Matrix", "Frankenstein",
        "Tokyo Sonata", "Jurassic Park", "Amores Perros",
        "Spring, Summer, Fall, Winter and Spring", "Naked", "Oldboy",
        "In the Mood for Love", "Bicycle Thieves", "Rashomon",
    ],
    "actors": [
        "Marlon Brando", "Sivaji Ganesan",
        "Robert De Niro", "Kamal Haasan",
        "Daniel Day-Lewis", "Leonardo DiCaprio",
    ],
}


# ═══════════════════════════════════════════════════════════════════════════
# 2. DOMAIN-RESTRICTED TRUSTED SOURCES
# ═══════════════════════════════════════════════════════════════════════════

TRUSTED_DOMAINS: list[dict[str, Any]] = [
    # ── ANALYSIS-FOCUSED sources (high priority) ────────────────────────
    {
        "domain": "sensesofcinema.com",
        "name": "Senses of Cinema",
        "knowledge_type": "director_analysis",
        "quality_bonus": 25,
    },
    {
        "domain": "bfi.org.uk",
        "name": "BFI / Sight & Sound",
        "knowledge_type": "film_theory",
        "quality_bonus": 25,
    },
    {
        "domain": "offscreen.com",
        "name": "Offscreen",
        "knowledge_type": "film_theory",
        "quality_bonus": 25,
    },
    {
        "domain": "lwlies.com",
        "name": "Little White Lies",
        "knowledge_type": "director_analysis",
        "quality_bonus": 22,
    },
    {
        "domain": "cinephiliabeyond.org",
        "name": "Cinephilia & Beyond",
        "knowledge_type": "director_analysis",
        "quality_bonus": 22,
    },
    {
        "domain": "filmcompanion.in",
        "name": "Film Companion",
        "knowledge_type": "film_criticism",
        "quality_bonus": 15,  # lower — many reviews mixed in
    },
    # ── REVIEW-HEAVY sources (only via --domains) ───────────────────────
    {
        "domain": "indiewire.com",
        "name": "IndieWire",
        "knowledge_type": "film_criticism",
        "quality_bonus": 15,
    },
    {
        "domain": "variety.com",
        "name": "Variety",
        "knowledge_type": "industry_analysis",
        "quality_bonus": 15,
    },
    {
        "domain": "rogerebert.com",
        "name": "RogerEbert.com",
        "knowledge_type": "film_criticism",
        "quality_bonus": 20,
    },
]

DOMAIN_LOOKUP = {d["domain"]: d for d in TRUSTED_DOMAINS}

# Default domains — verified working analysis-focused sites.
FAST_DOMAINS = [
    "sensesofcinema.com",
    "bfi.org.uk",
    "offscreen.com",
    "lwlies.com",
    "cinephiliabeyond.org",
    "filmcompanion.in",
]


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

# Aggressive timeouts — fail fast instead of waiting 15s per domain
HTTP_TIMEOUT = 6  # seconds (was 15)


# ─── State Management ──────────────────────────────────────────────────────

def load_state() -> dict:
    """Load previously scraped URLs + discovered entities."""
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"scraped_urls": [], "discovered_entities": []}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════
# 3. ENTITY-DRIVEN ARTICLE DISCOVERY (site-internal search)
# ═══════════════════════════════════════════════════════════════════════════

def _discover_senses_of_cinema(entity: str, max_results: int = 5) -> list[str]:
    """Senses of Cinema has a WordPress search at /?s=query."""
    query = quote_plus(entity)
    search_url = f"https://www.sensesofcinema.com/?s={query}"
    try:
        resp = SESSION.get(search_url, timeout=HTTP_TIMEOUT)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        urls = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "sensesofcinema.com" in href and any(
                p in href for p in ["/great-directors/", "/great-actors/",
                                     "/feature-articles/", "/cteq/"]
            ):
                if href not in urls:
                    urls.append(href)
                    if len(urls) >= max_results:
                        break
        return urls
    except requests.RequestException as e:
        log.debug("  Senses of Cinema search failed: %s", e)
        return []


def _discover_bfi(entity: str, max_results: int = 5) -> list[str]:
    """BFI: crawl features page and look for entity-related links."""
    urls = []
    entity_lower = entity.lower()
    entity_slug = entity_lower.replace(" ", "-").replace("'", "")

    # Try direct slug-based URL patterns
    candidate_urls = [
        f"https://www.bfi.org.uk/features/{entity_slug}",
        f"https://www.bfi.org.uk/sight-and-sound/{entity_slug}",
    ]
    for url in candidate_urls:
        try:
            resp = SESSION.head(url, timeout=HTTP_TIMEOUT, allow_redirects=True)
            if resp.status_code == 200:
                urls.append(url)
        except requests.RequestException:
            pass

    # Crawl features page for links mentioning the entity
    seed_pages = [
        "https://www.bfi.org.uk/features",
        "https://www.bfi.org.uk/sight-and-sound",
    ]
    for seed in seed_pages:
        try:
            resp = SESSION.get(seed, timeout=HTTP_TIMEOUT)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                text = a.get_text(strip=True).lower()
                if not href.startswith("http"):
                    href = f"https://www.bfi.org.uk{href}"
                if entity_lower in text or entity_slug in href:
                    if "/features/" in href or "/sight-and-sound/" in href:
                        if href not in urls:
                            urls.append(href)
                            if len(urls) >= max_results:
                                return urls
        except requests.RequestException:
            pass
    return urls[:max_results]


def _discover_filmcompanion(entity: str, max_results: int = 5) -> list[str]:
    """Film Companion: only accept /readers-articles/ (essays), skip reviews."""
    query = quote_plus(entity)
    search_url = f"https://www.filmcompanion.in/?s={query}"
    try:
        resp = SESSION.get(search_url, timeout=HTTP_TIMEOUT)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        urls = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "filmcompanion.in" not in href:
                continue
            # ONLY accept essay-style articles, reject reviews & listicles
            if "/readers-articles/" in href:
                if href not in urls:
                    urls.append(href)
            # Skip: /reviews/, /fc-lists/, /news/, /features/.../news/
            if len(urls) >= max_results:
                break
        return urls
    except requests.RequestException:
        return []


def _discover_offscreen(entity: str, max_results: int = 5) -> list[str]:
    """Offscreen: filter for /view/ articles (the actual essays)."""
    query = quote_plus(entity)
    search_url = f"https://offscreen.com/?s={query}"
    try:
        resp = SESSION.get(search_url, timeout=HTTP_TIMEOUT)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        urls = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "offscreen.com" not in href:
                continue
            # Only accept /view/ URLs — these are the actual essays
            if "/view/" in href:
                if href not in urls:
                    urls.append(href)
                    if len(urls) >= max_results:
                        break
        return urls
    except requests.RequestException:
        return []


def _discover_cinephilia_beyond(entity: str, max_results: int = 5) -> list[str]:
    """Cinephilia & Beyond: filter for actual article pages."""
    query = quote_plus(entity)
    entity_lower = entity.lower()
    search_url = f"https://cinephiliabeyond.org/?s={query}"
    try:
        resp = SESSION.get(search_url, timeout=HTTP_TIMEOUT)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        urls = []
        skip_paths = [
            "/tag/", "/page/", "/category/", "/author/",
            "/search", ".jpg", ".png", ".pdf", "#",
            "/about/", "/contact/", "/sponsorship/",
            "/press-and-testimonials/",
        ]
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "cinephiliabeyond.org" not in href:
                continue
            if not href.startswith("http"):
                continue
            # Must have a slug (not just homepage)
            path = href.rstrip("/").split("cinephiliabeyond.org")[-1]
            if len(path) < 5:
                continue  # Skip homepage, root paths
            if any(skip in href for skip in skip_paths):
                continue
            # Match entity in link text or URL
            text = a.get_text(strip=True).lower()
            if entity_lower in text or entity_lower.replace(" ", "-") in href.lower():
                if href not in urls:
                    urls.append(href)
                    if len(urls) >= max_results:
                        break
        return urls
    except requests.RequestException:
        return []


def _discover_lwlies(entity: str, max_results: int = 5) -> list[str]:
    """Little White Lies: accept /articles/ and /features/ only."""
    query = quote_plus(entity)
    search_url = f"https://lwlies.com/?s={query}"
    try:
        resp = SESSION.get(search_url, timeout=HTTP_TIMEOUT)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        urls = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "lwlies.com" not in href:
                continue
            if not href.startswith("http"):
                continue
            # Only accept articles and features, not reviews/nav
            if "/articles/" in href or "/features/" in href:
                if href not in urls:
                    urls.append(href)
                    if len(urls) >= max_results:
                        break
        return urls
    except requests.RequestException:
        return []


def _discover_generic_site(
    entity: str, domain: str, max_results: int = 5
) -> list[str]:
    """Fallback: try common search URL patterns for other domains."""
    query = quote_plus(entity)
    search_patterns = [
        f"https://www.{domain}/search?q={query}",
        f"https://www.{domain}/?s={query}",
        f"https://www.{domain}/search/?q={query}",
        f"https://{domain}/search?q={query}",
    ]

    entity_lower = entity.lower()
    urls = []

    for search_url in search_patterns:
        try:
            resp = SESSION.get(search_url, timeout=HTTP_TIMEOUT)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if not href.startswith("http"):
                    href = f"https://www.{domain}{href}"
                text = a.get_text(strip=True).lower()
                parsed = urlparse(href)
                if domain not in parsed.netloc:
                    continue
                # Skip non-article pages
                if any(skip in href for skip in [
                    "/tag/", "/page/", "/category/", "/author/",
                    "/search", ".jpg", ".png", ".pdf", "#",
                    "/login", "/subscribe", "/newsletter",
                    "/reviews/",  # Skip reviews
                ]):
                    continue
                if entity_lower in text or entity_lower.replace(" ", "-") in href:
                    if href not in urls:
                        urls.append(href)
                        if len(urls) >= max_results:
                            return urls
            if urls:
                break
        except requests.RequestException:
            continue

    return urls[:max_results]


# Map domains to their discovery functions
_DISCOVERY_HANDLERS: dict[str, Any] = {
    "sensesofcinema.com": _discover_senses_of_cinema,
    "bfi.org.uk": _discover_bfi,
    "filmcompanion.in": _discover_filmcompanion,
    "offscreen.com": _discover_offscreen,
    "cinephiliabeyond.org": _discover_cinephilia_beyond,
    "lwlies.com": _discover_lwlies,
}


def search_articles_for_entity(
    entity: str,
    domains: list[str] | None = None,
    max_results_per_domain: int = 5,
) -> list[dict[str, str]]:
    """
    Discover articles about an entity using site-internal search.
    Returns list of {url, domain, entity} dicts.
    """
    if domains is None:
        domains = FAST_DOMAINS  # Only use fast domains by default

    results: list[dict[str, str]] = []

    for domain in domains:
        handler = _DISCOVERY_HANDLERS.get(domain)
        if handler:
            urls = handler(entity, max_results=max_results_per_domain)
        else:
            urls = _discover_generic_site(
                entity, domain, max_results=max_results_per_domain
            )

        for url in urls:
            results.append({
                "url": url,
                "domain": domain,
                "entity": entity,
            })

        time.sleep(0.5)  # Polite delay between domains (reduced from 1.0)

    return results


# ═══════════════════════════════════════════════════════════════════════════
# 4. ARTICLE EXTRACTION (reused from v1)
# ═══════════════════════════════════════════════════════════════════════════

def extract_article(url: str) -> dict[str, Any] | None:
    """Download and extract article content using trafilatura."""
    import trafilatura

    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None

        text = trafilatura.extract(downloaded, include_comments=False)
        if not text:
            return None

        meta_json = trafilatura.extract(
            downloaded, output_format="json", include_comments=False,
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
        log.debug("  Extraction failed for %s: %s", url, e)
        return None


def clean_text(text: str) -> str | None:
    """Clean extracted article text. Returns None if too short."""
    nav_phrases = [
        r"skip to (?:main )?content", r"cookie (?:policy|consent|settings)",
        r"sign up for (?:our )?newsletter", r"subscribe (?:to|now)",
        r"all rights reserved", r"©\s*\d{4}",
        r"terms (?:of use|and conditions)", r"privacy policy",
        r"follow us on", r"share (?:this|on)",
    ]
    for pattern in nav_phrases:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 400:
        return None
    return text


# ═══════════════════════════════════════════════════════════════════════════
# 5. ENTITY DETECTION + CITATION EXPANSION
# ═══════════════════════════════════════════════════════════════════════════

_NLP = None


def _get_nlp():
    global _NLP
    if _NLP is None:
        import spacy
        _NLP = spacy.load("en_core_web_sm")
    return _NLP


def detect_entities(text: str) -> dict[str, list[str]]:
    """Extract people and film titles using spaCy NER."""
    nlp = _get_nlp()
    doc = nlp(text[:100_000])

    people: set[str] = set()
    films: set[str] = set()

    for ent in doc.ents:
        if ent.label_ == "PERSON":
            name = ent.text.strip()
            if len(name) > 2 and " " in name:
                people.add(name)
        elif ent.label_ == "WORK_OF_ART":
            title = ent.text.strip()
            if len(title) > 2:
                films.add(title)

    return {
        "directors": sorted(people),
        "actors": [],
        "films": sorted(films),
    }


# Known film figures — used to filter citation entities so we don't
# waste time searching for random academics/authors detected by NER.
_KNOWN_FILM_FIGURES: set[str] | None = None


def _get_known_film_figures() -> set[str]:
    """Build a set of known person names from the IMDb dataset."""
    global _KNOWN_FILM_FIGURES
    if _KNOWN_FILM_FIGURES is None:
        _KNOWN_FILM_FIGURES = set()
        # Add all seed entities as known
        for category in ENTITY_SEEDS.values():
            for name in category:
                _KNOWN_FILM_FIGURES.add(name.lower())
        # Try to load person index from KB
        person_index_path = DATA_DIR / "person_index.parquet"
        if person_index_path.exists():
            try:
                pdf = pd.read_parquet(person_index_path)
                if "primary_name" in pdf.columns:
                    names = pdf["primary_name"].dropna().str.lower().tolist()
                    _KNOWN_FILM_FIGURES.update(names[:50000])  # top 50k
                    log.info("Loaded %d names for citation filtering", len(_KNOWN_FILM_FIGURES))
            except Exception:
                pass
    return _KNOWN_FILM_FIGURES


def extract_citation_entities(entities: dict[str, list[str]]) -> list[str]:
    """
    From detected entities, produce new entity names for citation expansion.
    Only keep entities that look like real film figures (not academics/authors).
    """
    known = _get_known_film_figures()
    new_entities: list[str] = []

    for person in entities.get("directors", []):
        parts = person.split()
        # Only 2-3 word names (skip "Dorothy Theresa L. Geller" style)
        if len(parts) not in (2, 3):
            continue
        if not all(p[0].isupper() for p in parts if p):
            continue
        # Check against known film figures if index is available
        if known and person.lower() not in known:
            continue  # Skip unknown names
        new_entities.append(person)

    # Film titles — only if they match our IMDb index
    for film in entities.get("films", []):
        if len(film) > 3 and film[0].isupper():
            if _TITLE_INDEX and film.lower().strip() in _TITLE_INDEX:
                new_entities.append(film)

    return new_entities[:5]  # Hard cap to prevent queue explosion


# ═══════════════════════════════════════════════════════════════════════════
# 6. AUTO-CURATION QUALITY SCORING
# ═══════════════════════════════════════════════════════════════════════════

# ─── Analytical depth detection ─────────────────────────────────────────

ANALYSIS_KEYWORDS = [
    "mise-en-scene", "mise en scene", "cinematography", "auteur",
    "neorealism", "formalism", "semiotics", "subtext", "ideology",
    "dialectic", "aesthetic", "narrative structure", "thematic",
    "stylistic", "visual language", "symbolism", "allegory",
    "existential", "phenomenology", "film theory", "directorial",
    "oeuvre", "montage", "diegetic", "long take", "deep focus",
    "expressionism", "surrealism", "psychoanalytic", "feminist cinema",
    "postcolonial", "deconstructi", "intertextual", "film grammar",
    "blocking", "tableau", "chiaroscuro", "tracking shot",
]

REVIEW_KEYWORDS = [
    "stars", "rating", "review", "verdict", "watch it", "skip it",
    "recommended", "thumbs up", "out of 5", "/5", "/10",
    "box office", "opening weekend", "trailer", "release date",
    "streaming on", "now playing",
]


def score_article(
    text: str,
    domain: str,
    entities: dict[str, list[str]],
    scraped_texts_hashes: set[str],
) -> int:
    """
    Score an article for quality (0–100).
    Heavily favors analytical content over reviews.
    ≥60 → store, 40–60 → cache, <40 → discard
    """
    score = 0
    text_lower = text.lower()

    # Trusted domain bonus
    domain_info = DOMAIN_LOOKUP.get(domain)
    if domain_info:
        score += domain_info.get("quality_bonus", 0)

    # Article length (longer = more analytical)
    if len(text) >= 5000:
        score += 18
    elif len(text) >= 3000:
        score += 12
    elif len(text) >= 1000:
        score += 5

    # ──── ANALYTICAL DEPTH BONUS (key differentiator) ────
    analysis_hits = sum(1 for kw in ANALYSIS_KEYWORDS if kw in text_lower)
    if analysis_hits >= 5:
        score += 20  # Deep analysis
    elif analysis_hits >= 3:
        score += 12  # Moderate analysis
    elif analysis_hits >= 1:
        score += 5   # Some analytical language

    # ──── REVIEW PENALTY ────
    review_hits = sum(1 for kw in REVIEW_KEYWORDS if kw in text_lower)
    if review_hits >= 3:
        score -= 15  # Clearly a review
    elif review_hits >= 2:
        score -= 8

    # Film entities detected
    films = entities.get("films", [])
    if films:
        score += min(15, len(films) * 3)

    # Director/person entities detected
    people = entities.get("directors", [])
    if people:
        score += min(10, len(people) * 2)

    # Duplicate detection (content hash)
    content_hash = hashlib.md5(text[:2000].encode()).hexdigest()
    if content_hash in scraped_texts_hashes:
        score -= 20

    return max(0, min(100, score))


# ═══════════════════════════════════════════════════════════════════════════
# 7. CANONICAL IMDb MAPPING (reused from v1)
# ═══════════════════════════════════════════════════════════════════════════

_MOVIE_ENTITY: pd.DataFrame | None = None
_TITLE_INDEX: dict[str, str] | None = None


def _load_movie_entity() -> pd.DataFrame | None:
    global _MOVIE_ENTITY, _TITLE_INDEX
    if _MOVIE_ENTITY is None:
        path = DATA_DIR / "movie_entity.parquet"
        if path.exists():
            _MOVIE_ENTITY = pd.read_parquet(path)
            titles = _MOVIE_ENTITY["title"].astype(str).str.lower().str.strip()
            ids = _MOVIE_ENTITY["imdb_id"]
            _TITLE_INDEX = {}
            for t, iid in zip(titles, ids):
                if t not in _TITLE_INDEX:
                    _TITLE_INDEX[t] = iid
            log.info("Loaded movie_entity: %d rows, %d unique titles",
                     len(_MOVIE_ENTITY), len(_TITLE_INDEX))
        else:
            log.warning("movie_entity.parquet not found — IMDb mapping disabled")
    return _MOVIE_ENTITY


def map_to_imdb(film_titles: list[str]) -> list[str]:
    _load_movie_entity()
    if _TITLE_INDEX is None or not film_titles:
        return []

    matched: set[str] = set()
    for film in film_titles:
        ft = film.lower().strip()
        if ft in _TITLE_INDEX:
            matched.add(_TITLE_INDEX[ft])
            continue
        try:
            from rapidfuzz import fuzz, process as rfprocess
            result = rfprocess.extractOne(
                ft, _TITLE_INDEX.keys(), scorer=fuzz.ratio, score_cutoff=90
            )
            if result:
                matched.add(_TITLE_INDEX[result[0]])
        except ImportError:
            break

    return sorted(matched)


# ═══════════════════════════════════════════════════════════════════════════
# 8. RAG CHUNKING (reused from v1)
# ═══════════════════════════════════════════════════════════════════════════

def chunk_text(text: str, chunk_size: int = 1000, chunk_overlap: int = 150) -> list[str]:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    return splitter.split_text(text)


def save_record(record: dict, output_path: Path) -> None:
    with open(output_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ═══════════════════════════════════════════════════════════════════════════
# ARTICLE PROCESSING PIPELINE
# ═══════════════════════════════════════════════════════════════════════════

def process_article(
    url: str,
    entity: str,
    domain: str,
    scraped_texts_hashes: set[str],
) -> dict[str, Any] | None:
    """Full pipeline for a single article URL."""

    # 1. Extract
    extracted = extract_article(url)
    if not extracted or not extracted.get("text"):
        return None

    # 2. Clean
    cleaned = clean_text(extracted["text"])
    if not cleaned:
        return None

    # 3. Detect entities
    entities = detect_entities(cleaned)

    # 4. Score quality
    quality = score_article(cleaned, domain, entities, scraped_texts_hashes)
    if quality < 40:
        log.debug("  Discarded (score %d): %s", quality, url[:60])
        return None

    # 5. Map to IMDb
    imdb_ids = map_to_imdb(entities.get("films", []))

    # 6. Chunk
    chunks = chunk_text(cleaned)

    # 7. Extract citation entities for expansion
    citation_entities = extract_citation_entities(entities)

    # 8. Build domain info
    domain_info = DOMAIN_LOOKUP.get(domain, {})

    record = {
        "source": domain_info.get("name", domain),
        "knowledge_type": domain_info.get("knowledge_type", "film_analysis"),
        "title": extracted.get("title"),
        "author": extracted.get("author"),
        "publication_date": extracted.get("date"),
        "entity": entity,
        "entity_type": "search_seed",
        "entities": entities,
        "imdb_ids": imdb_ids,
        "text": cleaned,
        "chunks": chunks,
        "url": url,
        "quality_score": quality,
        "_citation_entities": citation_entities,
    }

    log.info(
        "  %s %s | score:%d | chunks:%d | imdb:%d | citations:%d",
        "✅" if quality >= 60 else "📦",
        (extracted.get("title") or "untitled")[:45],
        quality,
        len(chunks),
        len(imdb_ids),
        len(citation_entities),
    )

    return record


# ═══════════════════════════════════════════════════════════════════════════
# MAIN V2 PIPELINE
# ═══════════════════════════════════════════════════════════════════════════

def run_pipeline_v2(
    max_articles: int = 50,
    output_path: Path | None = None,
    dry_run: bool = False,
    workers: int = 8,
    expand_depth: int = 1,
    domains: list[str] | None = None,
) -> None:
    """
    Entity-driven crawling pipeline.

    expand_depth controls citation expansion:
      0 = seed entities only
      1 = seeds + entities discovered from seed articles
      2 = seeds + 1st-level + 2nd-level discovered (large)
    """
    if output_path is None:
        output_path = OUTPUT_DIR / "analysis_layer.jsonl"

    state = load_state()
    scraped_urls: set[str] = set(state.get("scraped_urls", []))
    discovered_entities: set[str] = set(state.get("discovered_entities", []))
    scraped_texts_hashes: set[str] = set()

    if domains is None:
        domains = [d["domain"] for d in TRUSTED_DOMAINS]

    # Build initial entity queue from seeds
    entity_queue: deque[tuple[str, int]] = deque()  # (entity, depth)
    all_seeds = (
        ENTITY_SEEDS.get("directors", [])
        + ENTITY_SEEDS.get("films", [])
        + ENTITY_SEEDS.get("actors", [])
    )
    for ent in all_seeds:
        if ent not in discovered_entities:
            entity_queue.append((ent, 0))

    total_saved = 0
    total_skipped = 0
    total_discarded = 0
    processed_entities: set[str] = set()

    while entity_queue and total_saved < max_articles:
        entity, depth = entity_queue.popleft()

        if entity in processed_entities:
            continue
        processed_entities.add(entity)

        log.info("═══ Entity: %s (depth %d) ═══", entity, depth)

        # Step 3: Search-based discovery
        search_results = search_articles_for_entity(
            entity, domains=domains,
            max_results_per_domain=3,
        )

        # Filter already-scraped
        new_urls = [r for r in search_results if r["url"] not in scraped_urls]
        if not new_urls:
            log.info("  No new URLs for entity '%s'", entity)
            continue

        # Limit per entity
        per_entity_limit = min(len(new_urls), max(3, (max_articles - total_saved)))
        new_urls = new_urls[:per_entity_limit]

        log.info("  Found %d new article URLs", len(new_urls))

        # Parallel extraction
        records: list[dict] = []
        with ThreadPoolExecutor(max_workers=min(workers, len(new_urls))) as executor:
            future_to_info = {
                executor.submit(
                    process_article,
                    r["url"], entity, r["domain"], scraped_texts_hashes,
                ): r
                for r in new_urls
            }

            for future in tqdm(
                as_completed(future_to_info),
                total=len(future_to_info),
                desc=f"  {entity[:25]}",
                unit="art",
            ):
                info = future_to_info[future]
                try:
                    result = future.result()
                    if result:
                        quality = result.get("quality_score", 0)
                        if quality >= 60:
                            records.append(result)
                            scraped_urls.add(info["url"])
                            # Add content hash for dedup
                            h = hashlib.md5(result["text"][:2000].encode()).hexdigest()
                            scraped_texts_hashes.add(h)
                        elif quality >= 40:
                            # Cache-quality: store but log as marginal
                            records.append(result)
                            scraped_urls.add(info["url"])
                            log.debug("  Cached (marginal quality %d): %s", quality, info["url"][:50])
                        else:
                            total_discarded += 1
                    else:
                        total_skipped += 1
                except Exception as e:
                    import traceback
                    log.error("  Error: %s\n%s", e, traceback.format_exc())
                    total_skipped += 1

        # Save records + extract citations
        for record in records:
            citation_ents = record.pop("_citation_entities", [])

            if not dry_run:
                save_record(record, output_path)

            # Citation expansion: add discovered entities to queue
            if depth < expand_depth:
                for ce in citation_ents:
                    if ce not in processed_entities and ce not in discovered_entities:
                        entity_queue.append((ce, depth + 1))
                        discovered_entities.add(ce)

        total_saved += len(records)
        log.info("  Entity '%s': %d articles saved | total: %d/%d",
                 entity, len(records), total_saved, max_articles)

    # Save state
    state = {
        "scraped_urls": sorted(scraped_urls),
        "discovered_entities": sorted(discovered_entities),
    }
    save_state(state)

    log.info("═══ V2 Pipeline complete ═══")
    log.info("  Articles saved:    %d", total_saved)
    log.info("  Skipped:           %d", total_skipped)
    log.info("  Discarded (low-q): %d", total_discarded)
    log.info("  Entities processed:%d", len(processed_entities))
    log.info("  Entity queue remaining: %d", len(entity_queue))
    if not dry_run:
        log.info("  Output: %s", output_path)


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="FilmDB v2 — Entity-Driven Film Essay Crawling Pipeline",
    )
    parser.add_argument(
        "--max-articles", type=int, default=50,
        help="Maximum total articles to scrape (default: 50)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output JSONL path (default: rag/scraped_articles/analysis_layer.jsonl)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Process articles but don't write JSONL output",
    )
    parser.add_argument(
        "--workers", type=int, default=8,
        help="Parallel download workers (default: 8)",
    )
    parser.add_argument(
        "--expand-depth", type=int, default=1,
        help="Citation expansion depth: 0=seeds only, 1=1-level, 2=2-level (default: 1)",
    )
    parser.add_argument(
        "--domains", nargs="+", default=None,
        help="Restrict to specific domains (e.g. bfi.org.uk sensesofcinema.com)",
    )

    args = parser.parse_args()
    output_path = Path(args.output) if args.output else None

    log.info("Starting FilmDB v2 entity-driven crawling pipeline")
    log.info("  Max articles: %d", args.max_articles)
    log.info("  Expand depth: %d", args.expand_depth)
    log.info("  Workers: %d", args.workers)
    log.info("  Dry run: %s", args.dry_run)
    log.info("  Domains: %s", args.domains or "all")

    run_pipeline_v2(
        max_articles=args.max_articles,
        output_path=output_path,
        dry_run=args.dry_run,
        workers=args.workers,
        expand_depth=args.expand_depth,
        domains=args.domains,
    )


if __name__ == "__main__":
    main()
