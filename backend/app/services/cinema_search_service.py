import json
import logging
import random
import urllib.parse
from datetime import datetime
from typing import Dict, Any, List

import httpx
import spacy
import trafilatura
from bs4 import BeautifulSoup

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None

from app.config import settings
from app.utils.tool_formatter import normalize_tool_output

logger = logging.getLogger(__name__)

# Phase 19: Performance optimization - simple in-memory cache for search results
_SEARCH_CACHE = {} 
_CACHE_TTL = 300 # 5 minutes

# Categorized trusted domains for cinema search
TAMIL_SITES = [
    "silverscreenindia.com", "cinemaexpress.com", "behindwoods.com", 
    "galatta.com", "thenewsminute.com"
]

INDIAN_SITES = [
    "filmcompanion.in", "thehindu.com", "indianexpress.com", "scroll.in", 
    "bollywoodhungama.com", "koimoi.com", "pinkvilla.com"
]

GLOBAL_SITES = [
    "sensesofcinema.com", "bfi.org.uk", "variety.com", "scroll.in", "indiewire.com", "hollywoodreporter.com", "deadline.com", 
    "empireonline.com", "collider.com", "rogerebert.com", "brightlightsfilm.com", "filmcomment.com", "criterion.com"
]

VIDEO_SITES = [
    "youtube.com", "vimeo.com"
]

AWARD_SITES = [
    "oscar.org", "festival-cannes.com", "iffi.gov.in"
]

# Combined flat list for legacy fallback or general broad searches
CINEMA_DOMAINS = TAMIL_SITES + INDIAN_SITES + GLOBAL_SITES + AWARD_SITES + VIDEO_SITES

# Load NLP models (lazy load to save memory during startup)
_nlp = None

def get_nlp():
    global _nlp
    if _nlp is None:
        try:
            _nlp = spacy.load("en_core_web_sm")
        except OSError:
            logger.warning("Spacy model 'en_core_web_sm' not found. Ensure you run: python -m spacy download en_core_web_sm")
            _nlp = None
    return _nlp

def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> List[str]:
    """Simple character-based sliding window chunker."""
    if not text:
        return []
    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + chunk_size, text_len)
        if end < text_len:
            boundary = max(text.rfind(" ", start, end), text.rfind("\n", start, end))
            # Only use boundary if it advances past the overlap
            if boundary > start + overlap:
                end = boundary
        chunks.append(text[start:end].strip())
        # Ensure forward progress
        start = max(start + 1, end - overlap)
    return [c for c in chunks if len(c) > 50]

def build_cinema_queries(user_query: str, priority_groups: List[str] | None = None) -> tuple[str, str]:
    """Build both a restricted primary query and a general web query."""
    refined_query = user_query
    lowered = user_query.lower()
    
    # Query Refinement Logic: Inject context for awards
    award_keywords = ["oscar", "academy award", "winners", "golden globe", "bafta", "national award"]
    if any(k in lowered for k in award_keywords):
        if "full" not in lowered and "list" not in lowered:
            refined_query = f"{user_query} full winners list nominees"
            logger.info(f"Refined query for award intent: {refined_query}")

    # Analytical intent detection: if query asks "why", "analysis", "essay", etc.
    analysis_keywords = ["why", "how", "analysis", "essay", "theme", "aesthetic", "theory", "meaning"]
    if any(k in lowered for k in analysis_keywords):
        if "essay" not in refined_query and "analysis" not in refined_query:
            refined_query = f"{refined_query} film analysis essay article"
            logger.info(f"Refined query for analytical intent: {refined_query}")

    # Video content specific refinement
    video_keywords = ["video", "youtube", "review", "galatta", "plus"]
    if any(k in lowered for k in video_keywords):
        # Specially prioritize Galatta Plus if mentioned or implicitly relevant
        if "galatta" in lowered or "plus" in lowered:
            refined_query = f"{user_query} Galatta Plus reviews"
            
    # Resolve domain filter for restricted query
    target_domains = []
    if priority_groups:
        for group in priority_groups:
            if group == "tamil": target_domains.extend(TAMIL_SITES)
            elif group == "indian": target_domains.extend(INDIAN_SITES)
            elif group == "global": target_domains.extend(GLOBAL_SITES)
            elif group == "awards": target_domains.extend(AWARD_SITES)
            elif group == "video": target_domains.extend(VIDEO_SITES)
    
    if not target_domains:
        target_domains = list(CINEMA_DOMAINS)
        # If user specifically asked for Galatta, ensure we include YouTube in restricted
        if "galatta" in lowered:
            if "youtube.com" not in target_domains:
                target_domains.append("youtube.com")

    # Add specific channel filter if Galatta Plus is likely the target
    domain_filters = []
    for domain in target_domains:
        if domain == "youtube.com" and ("galatta" in lowered or "plus" in lowered):
            domain_filters.append('site:youtube.com "@GalattaPlus"')
        else:
            domain_filters.append(f"site:{domain}")

    domain_filter_str = " OR ".join(domain_filters)
    restricted_query = f"{refined_query} ({domain_filter_str})"
    
    return restricted_query, refined_query

async def _fetch_serper_results(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Fetch search results from Serper API."""
    if not settings.SERPER_API_KEY:
        logger.error("SERPER_API_KEY is not set.")
        return []

    url = "https://google.serper.dev/search"
    headers = {
        "X-API-KEY": settings.SERPER_API_KEY,
        "Content-Type": "application/json"
    }
    payload = json.dumps({
        "q": query,
        "num": limit
    })

    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        try:
            resp = await client.post(url, headers=headers, data=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("organic", [])
        except Exception as e:
            logger.error(f"Serper API error: {e}")
            return []

def _extract_article_text(url: str) -> str | None:
    """Extract the main text body of an article."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        return trafilatura.extract(downloaded)
    except Exception as e:
        logger.warning(f"Failed to extract text from {url}: {e}")
        return None

def _extract_metadata(html: str) -> Dict[str, str | None]:
    """Extract metadata like title and author using BeautifulSoup."""
    try:
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.text if soup.title else None

        author = None
        tag = soup.find("meta", {"name": "author"})
        if tag:
            author = tag.get("content")

        return {
            "title": title,
            "author": author
        }
    except Exception as e:
        logger.warning(f"Failed to extract metadata: {e}")
        return {"title": None, "author": None}

def _extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    parsed = urllib.parse.urlparse(url)
    if "youtube.com" in parsed.netloc:
        if "v" in urllib.parse.parse_qs(parsed.query):
            return urllib.parse.parse_qs(parsed.query)["v"][0]
        # Handle /v/ or /embed/ if any
        path_parts = parsed.path.split("/")
        if "v" in path_parts or "embed" in path_parts:
            return path_parts[-1]
    elif "youtu.be" in parsed.netloc:
        return parsed.path.lstrip("/")
    return None

async def _fetch_youtube_transcript(video_id: str) -> str | None:
    """Fetch the transcript text for a YouTube video."""
    if not YouTubeTranscriptApi:
        return None
    try:
        # Running in a thread pool as get_transcript/fetch is blocking
        loop = asyncio.get_event_loop()
        client = YouTubeTranscriptApi()
        transcript_list = await loop.run_in_executor(
            None, lambda: client.fetch(video_id)
        )
        # Construct full text from fragments
        full_text = " ".join([item.text for item in transcript_list])
        return full_text
    except Exception as e:
        logger.warning(f"YouTube transcript error for {video_id}: {e}")
        return None

def _detect_entities(text: str) -> tuple[List[str], List[str]]:
    """Detect films (WORK_OF_ART) and people in the text."""
    # Temporarily disabled to eliminate huge CPU/GIL bottleneck during search
    return [], []

def _classify_article(text: str, title: str | None = None) -> str:
    """Classify the primary subject of the article based on keywords in text and title."""
    content = (text or "").lower()
    t_lower = (title or "").lower()
    combined = f"{t_lower} {content}"
    
    if not combined.strip():
        return "general_news"
    
    # Priority 0: Video Reviews (YouTube/Vimeo)
    if any(k in content for k in ["youtube.com", "vimeo.com", "watch?"]):
        return "video_review"

    # Priority 1: Analytical/Deep Content
    essay_keywords = ["essay", "thematic", "aesthetic", "theory", "philosophy", "analysis", "long-form", "deep dive", "critique"]
    if any(k in combined for k in essay_keywords):
        return "critic_essay"
        
    # Priority 2: Critic Reviews
    review_keywords = ["review", "stars", "rating:", "grade:", "verdict", "rx"]
    if any(k in combined for k in review_keywords):
        return "critic_review"
        
    # Priority 3: Industry & News
    if any(k in combined for k in ["box office", "grossed", "earnings", "collection"]):
        return "industry_news"
    if any(k in combined for k in ["won best", "oscars", "academy award", "nominee", "winner"]):
        return "award_result"
    if any(k in combined for k in ["festival", "cannes", "sundance", "iffi", "berlinale"]):
        return "festival_news"
    if any(k in combined for k in ["trailer", "upcoming", "release date", "first look"]):
        return "upcoming_movie"
        
    # Priority 4: Profiles & General Articles
    if any(k in combined for k in ["article", "feature", "profile", "interview"]):
        return "featured_article"
        
    return "general_news"

import asyncio

async def _process_result(result: dict, html: str | None) -> dict | None:
    url = result.get("link")
    if not url:
        return None
        
    try:
        # Pre-fetched HTML string directly to trafilatura extract
        text = trafilatura.extract(html) if html else None
        
        # YouTube Specific Enhancement: Transcript Fetching
        video_id = _extract_video_id(url)
        transcript = None
        if video_id:
            logger.info(f"Extracting transcript for {video_id}...")
            transcript = await _fetch_youtube_transcript(video_id)
            if transcript:
                # Append a chunk of transcript to the body for classification/summary
                # We limit to first 2500 chars to avoid prompt blowup
                transcript_snippet = transcript[:2500]
                text = f"[TRANSCRIPT EXCERPT] {transcript_snippet}\n\n[ORIGINAL DESCRIPTION] {text or ''}"

        metadata = _extract_metadata(html) if html else {"title": None, "author": None}
        
        summary = text[:800] + "..." if text else result.get("snippet", "")
        
        films, people = _detect_entities(text or summary)
        title_val = metadata.get("title") or result.get("title", "")
        article_type = _classify_article(text or summary, title=title_val)
        source_domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
        
        return {
            "source": source_domain,
            "title": metadata.get("title") or result.get("title", ""),
            "url": url,
            "type": article_type,
            "summary": summary,
            "published_date": result.get("date", "Unknown"),
            "detected_films": films[:5],
            "detected_people": people[:5],
            "author": metadata.get("author")
        }
    except Exception as e:
        logger.warning(f"Failed to process {url}: {e}")
        return None

async def run(query: str, limit: int = 6, priority_groups: List[str] | None = None) -> dict:
    """Execute dual web search (restricted and global) to ensure both quality and recall."""
    # Performance Optimization: Cache Check
    cache_key = f"{query}|{str(priority_groups)}"
    now = datetime.now().timestamp()
    if cache_key in _SEARCH_CACHE:
        entry = _SEARCH_CACHE[cache_key]
        if now - entry["timestamp"] < _CACHE_TTL:
            logger.info(f"Returning cached results for: {query}")
            return normalize_tool_output("success", {"results": entry["data"], "query": query})

    logger.info(f"Running dual cinema search for: {query}")
    
    restricted_q, global_q = build_cinema_queries(query, priority_groups=priority_groups)
    
    # Parallel Fetching
    restricted_pool_size = limit
    global_pool_size = limit // 2 if limit > 2 else 1
    
    restricted_task = _fetch_serper_results(restricted_q, limit=restricted_pool_size)
    global_task = _fetch_serper_results(global_q, limit=global_pool_size)
    
    res_restricted, res_global = await asyncio.gather(restricted_task, global_task)
    
    # Combine and prioritize: restricted results always come first for diversification
    combined_hits = {}
    
    for r in res_restricted:
        url = r.get("link")
        if url and url not in combined_hits:
            combined_hits[url] = r
            
    for r in res_global:
        url = r.get("link")
        if url and url not in combined_hits:
            combined_hits[url] = r
            
    results_pool = list(combined_hits.values())[:limit + 3]
    
    if not results_pool:
        return normalize_tool_output("success", {"results": [], "query": query})

    # Parallel HTTP Fetching with optimized limits
    async with httpx.AsyncClient(timeout=3.5, follow_redirects=True, limits=httpx.Limits(max_connections=20)) as client:
        fetch_tasks = []
        for res in results_pool:
            url = res.get("link")
            if url:
                fetch_tasks.append(client.get(url))
            else:
                async def _dummy(): return None
                fetch_tasks.append(_dummy())
                
        http_responses = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        
    htmls = [
        r.text if hasattr(r, "status_code") and r.status_code == 200 else None
        for r in http_responses
    ]

    # Parallel Processing/Extraction
    tasks = [_process_result(res, html) for res, html in zip(results_pool, htmls)]
    extracted = await asyncio.gather(*tasks)
    extracted_data = [item for item in extracted if item is not None][:limit]

    # Update Cache
    if extracted_data:
        _SEARCH_CACHE[cache_key] = {"timestamp": now, "data": extracted_data}
        if len(_SEARCH_CACHE) > 50:
            _SEARCH_CACHE.pop(next(iter(_SEARCH_CACHE)))

    return normalize_tool_output("success", {"results": extracted_data, "query": query})
