import json
import logging
import urllib.parse
from datetime import datetime
from typing import Dict, Any, List

import httpx
import spacy
import trafilatura
from bs4 import BeautifulSoup

from app.config import settings
from app.utils.tool_formatter import normalize_tool_output

logger = logging.getLogger(__name__)

# Authorized domains for cinema search
CINEMA_DOMAINS = [
    # Global Film Journalism
    "variety.com", "indiewire.com", "hollywoodreporter.com", "deadline.com",
    "empireonline.com", "collider.com",
    # Film Criticism & Essays
    "bfi.org.uk", "sensesofcinema.com", "brightlightsfilm.com", "rogerebert.com",
    # Indian Cinema
    "filmcompanion.in", "bollywoodhungama.com", "koimoi.com", "pinkvilla.com",
    "thehindu.com", "indianexpress.com",
    # Tamil Cinema
    "behindwoods.com", "galatta.com", "silverscreen.in", "cinemaexpress.com",
    "thenewsminute.com"
]

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

def build_cinema_query(user_query: str) -> str:
    """Build a search query restricted to the authorized domains."""
    domain_filter = " OR ".join([f"site:{domain}" for domain in CINEMA_DOMAINS])
    return f"{user_query} ({domain_filter})"

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

def _detect_entities(text: str) -> tuple[List[str], List[str]]:
    """Detect films (WORK_OF_ART) and people in the text."""
    # Temporarily disabled to eliminate huge CPU/GIL bottleneck during search
    return [], []

def _classify_article(text: str) -> str:
    """Classify the primary subject of the article based on keywords."""
    if not text:
        return "general_news"
    text = text.lower()
    
    if "review" in text:
        return "critic_review"
    if "box office" in text or "grossed" in text:
        return "industry_news"
    if "won best" in text or "oscars" in text or "award" in text:
        return "award_result"
    if "festival" in text or "cannes" in text or "sundance" in text:
        return "festival_news"
    if "trailer" in text or "upcoming" in text or "release date" in text:
        return "upcoming_movie"
        
    return "general_news"

import asyncio

async def _process_result(result: dict, html: str | None) -> dict | None:
    url = result.get("link")
    if not url:
        return None
        
    try:
        # Pass the pre-fetched HTML string directly to trafilatura extract
        text = trafilatura.extract(html) if html else None
        metadata = _extract_metadata(html) if html else {"title": None, "author": None}
        
        summary = text[:500] + "..." if text else result.get("snippet", "")
        
        films, people = _detect_entities(text or summary)
        article_type = _classify_article(text or summary)
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

async def run(query: str, limit: int = 3) -> dict:
    """Execute the domain-restricted cinema web search pipeline."""
    logger.info(f"Running cinema search for query: {query}")
    
    serper_query = build_cinema_query(query)
    results = await _fetch_serper_results(serper_query, limit=limit)
    
    if not results:
        return normalize_tool_output("success", {"results": [], "query": query})

    async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
        fetch_tasks = []
        for res in results:
            url = res.get("link")
            if url:
                fetch_tasks.append(client.get(url))
            else:
                # Dummy task to maintain ordering
                async def _dummy(): return None
                fetch_tasks.append(_dummy())
                
        http_responses = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        
    htmls = [
        r.text if getattr(r, "status_code", None) == 200 else None
        for r in http_responses
    ]

    tasks = [_process_result(res, html) for res, html in zip(results, htmls)]
    extracted = await asyncio.gather(*tasks)
    extracted_data = [item for item in extracted if item is not None]

    return normalize_tool_output("success", {"results": extracted_data[:5], "query": query})
