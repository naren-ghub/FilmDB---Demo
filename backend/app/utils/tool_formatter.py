

def normalize_tool_output(status: str, data: dict) -> dict:
    if status not in ("success", "not_found", "error"):
        status = "error"
    if data is None:
        data = {}
    return {"status": status, "data": data}


def summarize_tool_data(tool_name: str, output: dict) -> str:
    status = output.get("status")
    data = output.get("data", {})
    if status != "success":
        return f"{tool_name}: status={status}"

    if tool_name == "imdb":
        title = data.get("title")
        year = data.get("year")
        rating = data.get("rating")
        rating_count = data.get("rating_count")
        director = data.get("director")
        cast = data.get("cast", [])
        plot = data.get("plot", "")
        genres = data.get("genres", [])
        parts = [f"source: imdb title: {title} year: {year} rating: {rating}"]
        if rating_count:
            parts.append(f"votes: {rating_count}")
        if director:
            parts.append(f"director: {director}")
        if cast:
            parts.append(f"cast: {', '.join(cast[:5])}")
        if genres:
            parts.append(f"genres: {', '.join(genres[:5])}")
        if plot:
            parts.append(f"plot: {plot[:200]}")
        return " | ".join(parts)
    if tool_name == "wikipedia":
        summary = data.get("summary", "")
        return f"source: wikipedia summary: {summary[:180]}"
    if tool_name == "watchmode":
        platforms = data.get("platforms", []) or data.get("providers", [])
        return f"source: watchmode platforms: {', '.join(platforms) if platforms else 'none'}"
    if tool_name == "similarity":
        recs = data.get("recommendations", [])
        return f"source: similarity recommendations: {', '.join(recs)}"
    if tool_name == "archive":
        link = data.get("download_link", "")
        return f"source: archive download_link: {link or 'none'}"
    if tool_name == "web_search":
        summary = data.get("summary") or ""
        return f"source: web_search summary: {summary[:180]}"
    if tool_name in ("imdb_trending_tamil", "imdb_top_rated_english", "imdb_upcoming"):
        movies = data.get("movies", [])
        titles = [m.get("title") for m in movies if isinstance(m, dict) and m.get("title")]
        return f"source: {tool_name} titles: {', '.join(titles[:5])}"
    if tool_name == "imdb_person":
        name = data.get("name")
        profession = data.get("profession")
        return f"source: imdb_person name: {name} profession: {profession}"
    if tool_name == "rt_reviews":
        sentiment = data.get("sentiment")
        score = data.get("score")
        return f"source: rt_reviews sentiment: {sentiment} score: {score}"

    return f"{tool_name}: ok"


def summarize_all(tool_outputs: dict[str, dict]) -> list[str]:
    summaries = []
    for tool_name, output in tool_outputs.items():
        summaries.append(summarize_tool_data(tool_name, output))
    return summaries
