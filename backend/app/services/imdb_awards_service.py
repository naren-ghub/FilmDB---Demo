import httpx
import logging
from app.config import settings
from app.utils.tool_formatter import normalize_tool_output

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2

async def _request_with_retry(client: httpx.AsyncClient, url: str, headers: dict, params: dict) -> httpx.Response:
    """Make an HTTP GET with retry logic for transient failures."""
    last_error = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return resp
        except (httpx.TimeoutException, httpx.HTTPStatusError, Exception) as e:
            last_error = str(e)
            logger.warning(f"IMDb Awards API error: {url} - {e} (attempt {attempt + 1})")
            continue
    raise httpx.ConnectError(f"All {_MAX_RETRIES + 1} attempts failed: {last_error}")

_MAJOR_AWARDS_KEYWORDS = {"oscar", "academy", "golden globe", "bafta", "cannes", "venice", "berlin", "emmy"}

def _extract_awards(data: dict) -> dict:
    """Extract and group awards by event with a focus on notable wins/noms."""
    edges = (data.get("data") or {}).get("title") or {}
    edges = edges.get("awardNominations") or {}
    edges = edges.get("edges") or []
    
    events = {}
    major_awards = []
    wins_count = 0
    nominations_count = 0

    for edge in edges:
        node = edge.get("node", {})
        if not node: continue
        
        is_win = node.get("isWinner", False)
        
        category_data = node.get("category") or {}
        category = category_data.get("text", "Unknown Category") if isinstance(category_data, dict) else "Unknown Category"
        
        award_info = node.get("award") or {}
        award_name = award_info.get("awardName", "Award")
        
        event_edition = award_info.get("eventEdition") or {}
        year = event_edition.get("year", "Unknown Year")
        
        event_data = event_edition.get("event") or {}
        event_name = event_data.get("text", "Unknown Event")
        
        event_key = f"{event_name} ({year})"
        if event_key not in events:
            events[event_key] = {"wins": [], "nominations": []}
            
        award_entry = {
            "award": award_name,
            "category": category
        }
        
        if is_win:
            wins_count += 1
            events[event_key]["wins"].append(award_entry)
        else:
            nominations_count += 1
            events[event_key]["nominations"].append(award_entry)

        # Check for major awards for the summary
        full_text = (event_name + " " + award_name).lower()
        if any(keyword in full_text for keyword in _MAJOR_AWARDS_KEYWORDS):
            major_awards.append({
                "event": event_name,
                "award": award_name,
                "year": year,
                "category": category,
                "is_win": is_win
            })

    # Sort events by year descending
    sorted_events = dict(sorted(events.items(), key=lambda x: str(x[0].split('(')[-1]), reverse=True))

    return {
        "total_wins": wins_count,
        "total_nominations": nominations_count,
        "major_awards_summary": major_awards[:15],  # Top 15 major ones
        "awards_by_event": sorted_events
    }

async def run(imdb_id: str) -> dict:
    """Fetch structured award data from IMDb via imdb232 API."""
    if not settings.RAPIDAPI_KEY:
        return normalize_tool_output("error", {"reason": "missing_rapidapi_key"})

    host = settings.IMDB232_HOST
    url = f"https://{host}/api/title/get-awards-full"
    headers = {
        "X-RapidAPI-Key": settings.RAPIDAPI_KEY,
        "X-RapidAPI-Host": host,
    }
    # Increased limit to 50 to capture full history for popular films
    params = {"tt": imdb_id, "limit": "50"}

    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        try:
            resp = await _request_with_retry(client, url, headers, params)
            data = resp.json()
            if not data or "data" not in data:
                logger.error(f"IMDb Awards API structure error for {imdb_id}: {data}")
                return normalize_tool_output("not_found", {"imdb_id": imdb_id})
                
            extracted = _extract_awards(data)
            extracted["imdb_id"] = imdb_id
            return normalize_tool_output("success", extracted)
        except Exception as e:
            logger.error(f"IMDb Awards service failed for '{imdb_id}': {e}")
            return normalize_tool_output("error", {"imdb_id": imdb_id, "reason": str(e)})

