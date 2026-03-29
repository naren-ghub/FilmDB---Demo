import math


import pandas as pd
import numpy as np

def _sanitize_json(obj):
    """Recursively convert NaN/Infinity floats to None for JSON compliance.
    
    Handles: Python float NaN/Inf, numpy float/int/bool, pandas NA/NaT.
    """
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_json(v) for v in obj]
    # numpy types
    if isinstance(obj, np.floating):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    # Python float
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    # Pandas scalar NA / NaT (check AFTER dict/list/float to avoid ValueError)
    try:
        if pd.isna(obj):
            return None
    except (ValueError, TypeError):
        pass
    return obj

def normalize_tool_output(status: str, data: dict) -> dict:
    if status not in ("success", "not_found", "error", "disambiguation"):
        status = "error"
    if data is None:
        data = {}
    return {"status": status, "data": _sanitize_json(data)}


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
        meta = data.get("metadata", {})
        sections = data.get("structured_sections", {})
        
        parts = [f"source: {tool_name} title: {data.get('title')}"]
        parts.append(f"introduction: {summary[:350]}...")
        
        # 1. Surface Available Sections
        if sections:
            parts.append(f"available_sections: {', '.join(sections.keys())}")
            
            # 2. Surface a few more section snippets if small enough
            important_sections = ["Early life", "Career", "Style", "Legacy", "Reception"]
            for s_name in important_sections:
                if s_name in sections:
                    parts.append(f"{s_name.lower()}_snippet: {sections[s_name][:200]}...")
            
        # 3. Surface Awards & Accolades (Priority)
        awards = sections.get("Awards & Accolades")
        if awards:
            parts.append(f"awards_highlights: {awards[:300]}...")
            
        # 4. Surface External Connectivity
        links = meta.get("external_links", {})
        if links:
            links_list = [f"{k}: {v}" for k, v in links.items()]
            parts.append(f"external_links: [{', '.join(links_list)}]")
            
        # 5. Surface categories
        cats = meta.get("categories", [])
        if cats:
            parts.append(f"categories: {', '.join(cats[:8])}")
            
        return " | ".join(parts)
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

    if logical_name == "tmdb":
        if "name" in data:  # Person lookup
            name = data.get("name")
            prof = data.get("profession")
            bio = data.get("biography", "")
            known = data.get("known_for", [])
            parts = [f"source: tmdb name: {name} profession: {prof}"]
            if known:
                parts.append(f"known_for: {', '.join(known)}")
            
            # Add structured filmography snippets
            by_role = data.get("filmography_by_role", {})
            if by_role:
                for role, movies in list(by_role.items())[:4]:
                    titles = [f"{m['title']} ({m['year']})" for m in movies[:10]]
                    parts.append(f"{role}: {', '.join(titles)}")
            
            if bio:
                parts.append(f"biography: {bio[:200]}")
            return " | ".join(parts)
        else:  # Movie lookup
            title = data.get("title")
            year = data.get("year")
            rating = data.get("rating")
            director = data.get("director")
            cast = data.get("cast", [])
            plot = data.get("plot", "")
            genres = data.get("genres", [])
            tagline = data.get("tagline")
            runtime = data.get("runtime_minutes")
            
            parts = [f"source: tmdb title: {title} year: {year} rating: {rating}"]
            if runtime:
                parts.append(f"runtime: {runtime} min")
            if tagline:
                parts.append(f"tagline: {tagline}")
            if director:
                parts.append(f"director: {director}")
            if cast:
                parts.append(f"cast: {', '.join(cast[:5])}")
            if genres:
                parts.append(f"genres: {', '.join(genres[:5])}")
            if plot:
                parts.append(f"overview: {plot[:250]}")
            return " | ".join(parts)

    # ── KB tool summaries ────────────────────────────────────────────────

    if logical_name == "recommendation_engine":
        recs = data.get("recommendations", [])
        titles = [f"{r.get('title', 'Unknown')} ({r.get('year', '?')})" for r in recs[:10]]
        return f"source: {tool_name} recommendation_count: {len(recs)} recommendations: {', '.join(titles)}"

    if logical_name == "oscar_award":
        wins = data.get("wins", [])
        noms = data.get("nominations", [])
        parts = [f"source: {tool_name} oscar_wins: {len(wins)} oscar_nominations: {len(noms)}"]
        if wins:
            win_cats = [w.get("category", "") for w in wins[:5] if isinstance(w, dict)]
            parts.append(f"wins: {', '.join(win_cats)}")
        if noms:
            nom_cats = [n.get("category", "") for n in noms[:5] if isinstance(n, dict)]
            parts.append(f"nominations: {', '.join(nom_cats)}")
        return " | ".join(parts)

    if logical_name == "rag":
        passages = data.get("passages", [])
        query_type = data.get("query_type", "")
        parts = [f"source: rag_unified passage_count: {len(passages)} query_type: {query_type}"]
        for i, p in enumerate(passages[:7]):
            label = p.get("context_label") or p.get("entity_name") or p.get("title") or "unknown"
            snippet = p.get("passage", "")[:250].replace("\n", " ")
            score = p.get("score", 0)
            parts.append(f"chunk_{i+1}: [{label}] (score:{score:.3f}) {snippet}")
        return " | ".join(parts)

    if logical_name == "cinema_search":
        results = data.get("results", [])[:6]
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


def summarize_all(tool_outputs: dict[str, dict]) -> list[str]:
    summaries = []
    for tool_name, output in tool_outputs.items():
        summaries.append(summarize_tool_data(tool_name, output))
    return summaries

