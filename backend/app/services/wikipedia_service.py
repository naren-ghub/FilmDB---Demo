
import httpx
import urllib.parse
import logging

from app.config import settings
from app.utils.tool_formatter import normalize_tool_output

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2

# Wikipedia REST API requires a User-Agent header
_HEADERS = {
    "User-Agent": "FilmDB-Demo/1.0 (https://github.com/filmdb; filmdb@example.com)",
    "Accept": "application/json",
}


import re

def _parse_wikipedia_sections(extract: str) -> dict[str, str]:
    if not extract:
        return {}
    
    # Improved regex to catch == Level 2 == and === Level 3 === headers
    parts = re.split(r'\n(={2,4})\s+(.*?)\s+\1\n', '\n' + extract)
    sections = {}
    
    if parts:
        sections['Introduction'] = parts[0].strip()
        
    for i in range(1, len(parts), 3):
        header = parts[i+1].strip()
        content = parts[i+2].strip() if i+2 < len(parts) else ""
        sections[header] = content
        
    return sections

async def _get_image_urls(client: httpx.AsyncClient, filenames: list[str]) -> dict[str, str]:
    """Resolve file names to public URLs via Wikimedia API."""
    if not filenames:
        return {}
    
    url_map = {}
    # Filter out common icons/non-relevant files
    filtered = [f for f in filenames if not any(x in f.lower() for x in ['icon', 'logo', 'portal', 'padlock'])]
    
    for i in range(0, len(filtered), 50):
        batch = filtered[i:i+50]
        titles = "|".join(f"File:{f}" if not f.startswith("File:") else f for f in batch)
        
        params = {
            "action": "query",
            "titles": titles,
            "prop": "imageinfo",
            "iiprop": "url",
            "format": "json"
        }
        
        try:
            resp = await client.get("https://en.wikipedia.org/w/api.php", headers=_HEADERS, params=params)
            resp.raise_for_status()
            data = resp.json()
            pages = data.get("query", {}).get("pages", {})
            for p_id, p_val in pages.items():
                title = p_val.get("title", "")
                info = p_val.get("imageinfo", [])
                if info and title:
                    key = title.replace("File:", "")
                    url_map[key] = info[0].get("url")
        except Exception as e:
            logger.error(f"Failed to resolve image batch: {e}")
            
    return url_map

async def run(title: str) -> dict:
    clean_title = title.strip()
    url = "https://en.wikipedia.org/w/api.php"
    
    # We add 'images', 'extlinks', and 'categories' to 'prop'
    params = {
        "action": "query",
        "prop": "pageimages|extracts|images|extlinks|categories",
        "piprop": "thumbnail",
        "pithumbsize": "500",
        "explaintext": "1",
        "titles": clean_title,
        "format": "json",
        "redirects": "1",
        "clshow": "!hidden",
        "imlimit": "50",
        "ellimit": "500"
    }

    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        page_data = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await client.get(url, headers=_HEADERS, params=params)
                resp.raise_for_status()
                payload = resp.json()
                
                pages = payload.get("query", {}).get("pages", {})
                if "-1" in pages:
                    if attempt == 0:
                        params["titles"] = clean_title.title()
                        continue
                    return normalize_tool_output("not_found", {"title": clean_title})
                
                page_data = list(pages.values())[0]
                break
            except Exception as e:
                logger.warning(f"Wikipedia error for '{clean_title}': {e}")
                continue
        else:
            return normalize_tool_output("error", {"title": clean_title, "reason": "Max retries reached or page not found"})
            
        if not page_data:
            return normalize_tool_output("error", {"title": clean_title, "reason": "empty response"})

        # 1. Parse Sections (Deep nested regex)
        extract = page_data.get("extract", "")
        sections_dict = _parse_wikipedia_sections(extract)
        
        # 2. Extract Images & Resolve URLs (Uses the active client)
        raw_images = [img.get("title", "").replace("File:", "") for img in page_data.get("images", [])]
        clean_filenames = [f for f in raw_images if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
        image_gallery = await _get_image_urls(client, clean_filenames)

        # 3. Extract External Links (Check both metadata AND text content)
        ext_metadata_links = [l.get("*", "") for l in page_data.get("extlinks", [])]
        if not ext_metadata_links:
            ext_text = sections_dict.get("External links", "")
            ext_metadata_links = re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', ext_text)

        filtered_links = {
            "imdb": next((l for l in ext_metadata_links if "imdb.com/title" in l), None),
            "rotten_tomatoes": next((l for l in ext_metadata_links if "rottentomatoes.com/m/" in l or "rottentomatoes.com/movies/" in l), None),
            "metacritic": next((l for l in ext_metadata_links if "metacritic.com/movie/" in l), None),
            "official": next((l for l in ext_metadata_links if "official" in l.lower() or "website" in l.lower()), None)
        }

        # 4. Extract Categories
        categories = [c.get("title", "").replace("Category:", "") for c in page_data.get("categories", [])]

        # 5. Header Normalization (Awards & Accolades)
        AWARD_SYNONYMS = ["award", "accolade", "recognition", "honour", "achievement", "nomination"]
        structured_data = {}
        awards_content = []

        for header, content in sections_dict.items():
            if not content: continue
            if header == 'Introduction': continue
            
            if any(syn in header.lower() for syn in AWARD_SYNONYMS):
                awards_content.append(f"### {header}\n{content}")
                structured_data["Awards & Accolades"] = "\n\n".join(awards_content)
            else:
                structured_data[header] = content

        data = {
            "title": page_data.get("title") or clean_title,
            "summary": sections_dict.get("Introduction", ""),
            "metadata": {
                "image_gallery": image_gallery,
                "external_links": {k: v for k, v in filtered_links.items() if v},
                "categories": categories,
                "main_thumbnail": (page_data.get("thumbnail") or {}).get("source")
            },
            "structured_sections": structured_data
        }
        return normalize_tool_output("success", data)
