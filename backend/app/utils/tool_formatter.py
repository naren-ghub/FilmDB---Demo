


def normalize_tool_output(status: str, data: dict) -> dict:
    if status not in ("success", "not_found", "error", "disambiguation"):
        status = "error"
    if data is None:
        data = {}
    return {"status": status, "data": data}


def summarize_tool_data(tool_name: str, output: dict) -> str:
    status = output.get("status")
    data = output.get("data", {})
    
    # Allow mapping for comparison B-calls (e.g. wikipedia_b -> wikipedia)
    logical_name = tool_name
    if tool_name.endswith("_b"):
        logical_name = tool_name[:-2]

    if status == "disambiguation":
        candidates = data.get("candidates", [])
        cand_list = [f"{c.get('title')} ({c.get('year')})" for c in candidates[:5]]
        return f"{tool_name}: status=disambiguation | Multiple matches found: {', '.join(cand_list)}"

    if status != "success":
        return f"{tool_name}: status={status}"

    if logical_name == "imdb":
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
    if logical_name == "wikipedia":
        summary = data.get("summary", "")
        return f"source: {tool_name} summary: {summary[:180]}"
    if logical_name == "watchmode":
        platforms = data.get("platforms", []) or data.get("providers", [])
        return f"source: {tool_name} platforms: {', '.join(platforms) if platforms else 'none'}"
    if logical_name == "similarity":
        recs = data.get("recommendations", [])
        return f"source: {tool_name} recommendations: {', '.join(recs)}"
    if logical_name == "archive":
        link = data.get("download_link", "")
        return f"source: {tool_name} download_link: {link or 'none'}"


    if logical_name == "imdb_awards":
        wins = data.get("total_wins", 0)
        noms = data.get("total_nominations", 0)
        events = data.get("awards_by_event", {})
        parts = [f"source: {tool_name} total_wins: {wins} total_nominations: {noms}"]
        for event, details in list(events.items())[:8]:
            event_strs = []
            if details.get("wins"):
                win_cats = [w.get("category", "") for w in details["wins"] if isinstance(w, dict)]
                event_strs.append(f"wins: {', '.join(win_cats)}")
            if details.get("nominations"):
                nom_cats = [n.get("category", "") for n in details["nominations"] if isinstance(n, dict)]
                event_strs.append(f"nominations: {', '.join(nom_cats)}")
            parts.append(f"event: {event} ({' | '.join(event_strs)})")
        return " | ".join(parts)

    # ── KB tool summaries ────────────────────────────────────────────────
    if logical_name == "kb_entity":
        title = data.get("title")
        year = data.get("year")
        rating = data.get("imdb_rating")
        overview = data.get("overview", "")
        genres = data.get("genres", "")
        parts = [f"source: {tool_name} title: {title} year: {year} rating: {rating}"]
        if genres:
            parts.append(f"genres: {genres}")
        if overview:
            parts.append(f"overview: {str(overview)[:200]}")
        return " | ".join(parts)

    if logical_name == "kb_plot":
        title = data.get("title", "")
        plot = data.get("plot_text", "")
        return f"source: {tool_name} title: {title} plot: {str(plot)[:300]}"

    if logical_name == "kb_critic":
        title = data.get("title", "")
        count = data.get("review_count", 0)
        sentiments = data.get("sentiment_breakdown", {})
        reviews = data.get("reviews", [])
        review_texts = [r.get("review_text", "")[:100] for r in reviews[:5]]
        parts = [f"source: {tool_name} title: {title} review_count: {count} sentiments: {sentiments}"]
        for i, rt in enumerate(review_texts):
            parts.append(f"review_{i+1}: {rt}")
        return " | ".join(parts)

    if logical_name == "kb_similarity":
        recs = data.get("recommendations", [])
        titles = [r.get("title", "Unknown") for r in recs[:10]]
        tags = data.get("source_tags", [])
        return f"source: {tool_name} tags: {', '.join(tags[:5])} recommendations: {', '.join(titles)}"

    if logical_name == "kb_top_rated":
        movies = data.get("movies", [])
        titles = [f"{m.get('title')} ({m.get('rating')})" for m in movies[:10]]
        filters = data.get("filters", {})
        return f"source: {tool_name} filters: {filters} movies: {', '.join(titles)}"

    if logical_name == "kb_filmography":
        name = data.get("name")
        prof = data.get("professions", "")
        by_role = data.get("filmography_by_role", {})
        parts = [f"source: {tool_name} name: {name} profession: {prof}"]
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

    if logical_name == "kb_comparison":
        a = data.get("movie_a", {})
        b = data.get("movie_b", {})
        return (
            f"source: {tool_name} "
            f"movie_a: {a.get('title')} ({a.get('year')}) rating: {a.get('imdb_rating')} | "
            f"movie_b: {b.get('title')} ({b.get('year')}) rating: {b.get('imdb_rating')}"
        )

    if logical_name == "kb_film_analysis":
        articles = data.get("articles", [])
        count = data.get("article_count", 0)
        parts = [f"source: {tool_name} article_count: {count}"]
        for i, art in enumerate(articles[:3]):
            source = art.get("source", "?")
            title = art.get("title") or "untitled"
            chunks = art.get("analysis_chunks", [])
            chunk_text = " ".join(chunks[:2])[:300] if chunks else ""
            parts.append(
                f"article_{i+1}: [{source}] {title} | analysis: {chunk_text}"
            )
        return " | ".join(parts)

    if logical_name == "cinema_search":
        results = data.get("results", [])[:5]
        if not results:
            return f"source: {tool_name} query: {data.get('query', '')} | no results found"
        parts = [f"source: {tool_name} query: {data.get('query', '')}"]
        for r in results:
            source = r.get("source", "")
            title = r.get("title", "")
            summary = r.get("summary", "") 
            article_type = r.get("type", "")
            relevance = r.get("relevance_score", 0.0)
            
            entry = f"[{source}] {title} ({article_type})"
            if relevance > 0:
                entry += f" [Relevance: {relevance:.2f}]"
            entry += f"\nSnippet: {summary}"
            
            films = r.get("detected_films", [])
            people = r.get("detected_people", [])
            if films:
                entry += f"\nFilms mentioned: {', '.join(films[:5])}"
            if people:
                entry += f"\nPeople mentioned: {', '.join(people[:5])}"
            
            parts.append(entry)
        return "\n\n".join(parts)

    return f"{tool_name}: ok"

    return f"{tool_name}: ok"


def summarize_all(tool_outputs: dict[str, dict]) -> list[str]:
    summaries = []
    for tool_name, output in tool_outputs.items():
        summaries.append(summarize_tool_data(tool_name, output))
    return summaries
