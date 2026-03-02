import httpx

from app.config import settings
from app.utils.tool_formatter import normalize_tool_output


def _compute_sentiment(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 60:
        return "positive"
    if score >= 40:
        return "mixed"
    return "negative"


async def run(title: str) -> dict:
    if not settings.RT_API_KEY:
        return normalize_tool_output("error", {"reason": "missing_rt_api_key"})

    headers = {
        "X-RapidAPI-Key": settings.RT_API_KEY,
        "X-RapidAPI-Host": settings.RT_HOST,
    }
    url = f"https://{settings.RT_HOST}{settings.RT_REVIEWS_PATH}"
    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as client:
        try:
            resp = await client.get(url, headers=headers, params={"title": title})
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return normalize_tool_output("error", {"title": title})

    reviews = payload.get("reviews") or payload.get("results") or []
    score = payload.get("score") or payload.get("tomatometer") or payload.get("rating")
    try:
        score_val = float(score) if score is not None else None
    except Exception:
        score_val = None

    sentiment = _compute_sentiment(score_val)
    data = {
        "title": title,
        "sentiment": sentiment,
        "score": score_val,
        "review_count": len(reviews) if isinstance(reviews, list) else 0,
    }
    return normalize_tool_output("success", data)
