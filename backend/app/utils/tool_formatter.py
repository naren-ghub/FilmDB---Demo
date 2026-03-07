


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

    # ── KB tool summaries ────────────────────────────────────────────────
    if tool_name == "kb_entity":
        title = data.get("title")
        year = data.get("year")
        rating = data.get("imdb_rating")
        overview = data.get("overview", "")
        genres = data.get("genres", "")
        parts = [f"source: kb_entity title: {title} year: {year} rating: {rating}"]
        if genres:
            parts.append(f"genres: {genres}")
        if overview:
            parts.append(f"overview: {str(overview)[:200]}")
        return " | ".join(parts)

    if tool_name == "kb_plot":
        title = data.get("title", "")
        plot = data.get("plot_text", "")
        return f"source: kb_plot title: {title} plot: {str(plot)[:300]}"

    if tool_name == "kb_critic":
        title = data.get("title", "")
        count = data.get("review_count", 0)
        sentiments = data.get("sentiment_breakdown", {})
        reviews = data.get("reviews", [])
        review_texts = [r.get("review_text", "")[:100] for r in reviews[:5]]
        parts = [f"source: kb_critic title: {title} review_count: {count} sentiments: {sentiments}"]
        for i, rt in enumerate(review_texts):
            parts.append(f"review_{i+1}: {rt}")
        return " | ".join(parts)

    if tool_name == "kb_similarity":
        recs = data.get("recommendations", [])
        titles = [r.get("title", "Unknown") for r in recs[:10]]
        tags = data.get("source_tags", [])
        return f"source: kb_similarity tags: {', '.join(tags[:5])} recommendations: {', '.join(titles)}"

    if tool_name == "kb_top_rated":
        movies = data.get("movies", [])
        titles = [f"{m.get('title')} ({m.get('rating')})" for m in movies[:10]]
        filters = data.get("filters", {})
        return f"source: kb_top_rated filters: {filters} movies: {', '.join(titles)}"

    if tool_name == "kb_filmography":
        name = data.get("name")
        prof = data.get("professions", "")
        by_role = data.get("filmography_by_role", {})
        parts = [f"source: kb_filmography name: {name} profession: {prof}"]
        role_order = ["director", "writer", "producer", "actor", "actress",
                      "composer", "cinematographer", "editor", "self",
                      "archive_footage", "archive_sound"]
        for role in role_order:
            entries = by_role.get(role, [])
            if entries:
                titles = [f"{f.get('title')} ({f.get('year')}, rating={f.get('rating')})"
                          for f in entries[:15] if f.get("title")]
                parts.append(f"{role}: {', '.join(titles)}")
        # Fallback to flat list if grouped data is missing
        if not by_role:
            films = data.get("filmography", [])
            film_titles = [f"{f.get('title')} ({f.get('year')})" for f in films[:10] if f.get("title")]
            parts.append(f"films: {', '.join(film_titles)}")
        return " | ".join(parts)

    if tool_name == "kb_comparison":
        a = data.get("movie_a", {})
        b = data.get("movie_b", {})
        return (
            f"source: kb_comparison "
            f"movie_a: {a.get('title')} ({a.get('year')}) rating: {a.get('imdb_rating')} | "
            f"movie_b: {b.get('title')} ({b.get('year')}) rating: {b.get('imdb_rating')}"
        )

    return f"{tool_name}: ok"


def summarize_all(tool_outputs: dict[str, dict]) -> list[str]:
    summaries = []
    for tool_name, output in tool_outputs.items():
        summaries.append(summarize_tool_data(tool_name, output))
    return summaries
