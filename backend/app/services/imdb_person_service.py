import httpx

from app.config import settings
from app.utils.tool_formatter import normalize_tool_output


def _pick_person_id(payload: dict) -> str | None:
    results = payload.get("results") or payload.get("names") or []
    if isinstance(results, list) and results:
        first = results[0]
        imdb_id = first.get("id") or first.get("nconst")
        if isinstance(imdb_id, str):
            return imdb_id
    return None


def _normalize_person(payload: dict) -> dict:
    name = payload.get("name") or payload.get("title")
    birth_date = payload.get("birthDate") or payload.get("birthdate")
    profession = payload.get("profession") or payload.get("primaryProfession")
    known_for = payload.get("knownFor") or payload.get("knownForTitles") or []
    filmography = payload.get("filmography") or payload.get("credits") or []
    biography = payload.get("bio") or payload.get("biography") or payload.get("summary")
    poster = None
    image = payload.get("image") or payload.get("primaryImage")
    if isinstance(image, dict):
        poster = image.get("url") or image.get("imageUrl")
    elif isinstance(image, str):
        poster = image

    return {
        "name": name,
        "birth_date": birth_date,
        "profession": profession,
        "known_for": known_for,
        "filmography": filmography,
        "biography": biography,
        "poster_url": poster,
    }


async def run(name: str | None = None, imdb_id: str | None = None) -> dict:
    if not settings.RAPIDAPI_KEY:
        return normalize_tool_output("error", {"reason": "missing_rapidapi_key"})

    headers = {
        "X-RapidAPI-Key": settings.RAPIDAPI_KEY,
        "X-RapidAPI-Host": settings.IMDB_HOST,
    }

    if not imdb_id and name:
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
            try:
                find_url = f"https://{settings.IMDB_HOST}/name/find"
                find_resp = await client.get(find_url, headers=headers, params={"q": name})
                find_resp.raise_for_status()
                imdb_id = _pick_person_id(find_resp.json())
            except Exception:
                return normalize_tool_output("error", {"name": name})

    if not imdb_id:
        return normalize_tool_output("not_found", {"name": name})

    headers_person = {
        "X-RapidAPI-Key": settings.RAPIDAPI_KEY,
        "X-RapidAPI-Host": settings.IMDB236_HOST,
    }
    url = f"https://{settings.IMDB236_HOST}/api/imdb/name/{imdb_id}"
    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        try:
            resp = await client.get(url, headers=headers_person)
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return normalize_tool_output("error", {"imdb_id": imdb_id})

    data = _normalize_person(payload if isinstance(payload, dict) else {})
    data["imdb_id"] = imdb_id
    data["name"] = data.get("name") or name
    return normalize_tool_output("success", data)
