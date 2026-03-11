import json
import logging
from typing import Dict, Any, List

import spacy
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Constants based on the curated pipeline spec
CURATED_DIRECTORS = [
    "kubrick", "tarkovsky", "bergman", "bresson", "kurosawa",
    "ray", "scorsese", "miyazaki", "nolan", "villeneuve"
]

try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    logger.warning("Spacy model 'en_core_web_sm' not found. It must be downloaded before running.")
    nlp = None

class AnalysisExtractor:
    """Extracts entities and maps them to Canonical IDs."""
    
    def __init__(self, tmdbservice_fallback: Any = None):
        """
        Args:
            tmdbservice_fallback: A service to resolve TMDB/IMDB IDs if needed.
        """
        self.tmdb_service = tmdbservice_fallback

    def extract_entities(self, text: str) -> tuple[List[str], List[str]]:
        """
        Identify PEOPLE and WORKS OF ART from the text.
        """
        if not nlp:
            return [], []
        
        doc = nlp(text)
        people = []
        works = []
        
        for ent in doc.ents:
            if ent.label_ == "PERSON":
                people.append(ent.text)
            elif ent.label_ == "WORK_OF_ART":
                works.append(ent.text)
                
        # Deduplicate while preserving order
        people = list(dict.fromkeys(people))
        works = list(dict.fromkeys(works))
        
        return people, works

    def filter_curated_directors(self, people: List[str]) -> List[str]:
        """
        Keep only people who match our curated directors list.
        """
        matched_directors = []
        for person in people:
            p_lower = person.lower()
            if any(d in p_lower for d in CURATED_DIRECTORS):
                matched_directors.append(person)
        return matched_directors

    def get_canonical_id_for_title(self, title: str) -> str:
        """
        Attempt to resolve a movie title to an IMDB ID.
        This is a placeholder that will hook into the real TMDB service.
        """
        if not self.tmdb_service:
            return ""
            
        try:
            # We would typically call an async TMDB search here, but since crawlers 
            # often run sync, we might need an adapter or just use a local parquet lookup.
            # Returning empty let's the orchestrator decide how to handle it.
            return ""
        except Exception as e:
            logger.error(f"Failed to lookup canonical ID for {title}: {e}")
            return ""

    def process_article(self, url: str, source_name: str, title: str, text: str, author: str = "") -> List[Dict[str, Any]]:
        """
        Process the raw article text, extract entities, and format into the dataset schema.
        Returns a list of records (one for each major entity found, usually a film or director).
        """
        records = []
        people, works = self.extract_entities(text)
        directors = self.filter_curated_directors(people)
        
        # We create a record for the director if they are mentioned
        for director in directors:
            records.append({
                "imdb_id": "", # Person ID if we support it, otherwise leave blank or use name
                "entity_type": "person",
                "entity_name": director,
                "knowledge_type": "film_analysis",
                "source": source_name,
                "title": title,
                "author": author,
                "text": text,
                "url": url
            })
            
        # We create a record for each work of art mentioned
        # In a production system, we'd aggressively filter these to ensure they are actually movies
        for work in works[:5]: # Cap to top 5 works to avoid noise
            # Only consider works that are not too short (e.g., "The" is a common false positive)
            if len(work) > 3:
                records.append({
                    "imdb_id": self.get_canonical_id_for_title(work),
                    "entity_type": "film",
                    "entity_name": work,
                    "knowledge_type": "film_analysis",
                    "source": source_name,
                    "title": title,
                    "author": author,
                    "text": text,
                    "url": url
                })
                
        # If no specific entities found but we crawled it from a trusted source, 
        # save it as a generic theory piece
        if not records:
            records.append({
                "imdb_id": "",
                "entity_type": "theme",
                "entity_name": "",
                "knowledge_type": "film_analysis",
                "source": source_name,
                "title": title,
                "author": author,
                "text": text,
                "url": url
            })
            
        return records
