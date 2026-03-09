
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
        
    parts = re.split(r'\n==\s+(.*?)\s+==\n', '\n' + extract)
    sections = {}
    
    if parts:
        sections['Introduction'] = parts[0].strip()
        
    for i in range(1, len(parts), 2):
        header = parts[i].strip()
        content = parts[i+1].strip() if i+1 < len(parts) else ""
        sections[header] = content
        
    return sections

async def run(title: str) -> dict:
    clean_title = title.strip()
    url = "https://en.wikipedia.org/w/api.php"
    
    params = {
        "action": "query",
        "prop": "pageimages|extracts",
        "piprop": "thumbnail",
        "pithumbsize": "500",
        "explaintext": "1",
        "titles": clean_title,
        "format": "json",
        "redirects": "1"
    }

    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        last_error = None
        payload = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await client.get(url, headers=_HEADERS, params=params)
                resp.raise_for_status()
                payload = resp.json()
                
                pages = payload.get("query", {}).get("pages", {})
                if "-1" in pages:
                    # Page not found. Retry once with Title Case.
                    if attempt == 0:
                        params["titles"] = clean_title.title()
                        continue
                    return normalize_tool_output("not_found", {"title": clean_title})
                
                # Success
                page_data = list(pages.values())[0]
                break
            except httpx.TimeoutException:
                last_error = "timeout"
                logger.warning(f"Wikipedia timeout for '{clean_title}' (attempt {attempt + 1})")
                continue
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Wikipedia error for '{clean_title}' (attempt {attempt + 1}): {e}")
                continue
        else:
            return normalize_tool_output("error", {"title": clean_title, "reason": last_error})
            
    if not page_data:
        return normalize_tool_output("error", {"title": clean_title, "reason": "empty response"})

    extract = page_data.get("extract", "")
    sections_dict = _parse_wikipedia_sections(extract)
    
    structured_data = {}
    
    for header, content in sections_dict.items():
        if not content: continue
        
        if header == 'Introduction':
            continue # Handled as summary
            
        # Include all sections without filtering or capping as requested
        structured_data[header] = content

    data = {
        "title": page_data.get("title") or clean_title,
        "summary": sections_dict.get("Introduction", ""),
        "structured_sections": structured_data,
        "thumbnail": (page_data.get("thumbnail") or {}).get("source"),
    }
    return normalize_tool_output("success", data)
