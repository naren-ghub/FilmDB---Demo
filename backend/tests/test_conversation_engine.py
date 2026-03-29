import pytest

from app.conversation_engine import ConversationEngine
from app.layout_policy import select_layout_segments


@pytest.mark.asyncio
async def test_build_response_mapping():
    engine = ConversationEngine()
    tool_outputs = {
        "imdb": {"status": "success", "data": {"poster_url": "poster"}},
        "watchmode": {"status": "success", "data": {"providers": ["Netflix"]}},
        "similarity": {"status": "success", "data": {"recommendations": ["A", "B"]}},
        "archive": {"status": "success", "data": {"download_link": "link"}},
    }

    response = engine._build_response("hello", tool_outputs)

    assert response["poster_url"] == "poster"
    assert response["streaming"] == ["Netflix"]
    assert response["recommendations"] == ["A", "B"]
    assert response["download_link"] == "link"


def _make_response(**kwargs) -> dict:
    """Minimal response dict with sensible defaults for segment tests."""
    base = {
        "entity_type": "",
        "poster_url": "",
        "awards": {},
        "streaming": [],
        "recommendations": [],
        "download_link": "",
        "sources": [],
        "trailer_key": "",
        "filmography": {},
    }
    base.update(kwargs)
    return base


def test_segments_movie_with_poster_awards_streaming():
    """Movie with poster, awards, streaming → MOVIE_CARD hero + TRAILER + AWARDS + STREAMING."""
    tool_outputs = {
        "tmdb": {"status": "success", "data": {}},
        "oscar_award": {"status": "success", "data": {}},
        "watchmode": {"status": "success", "data": {}},
    }
    response = _make_response(
        entity_type="movie",
        poster_url="https://example.com/poster.jpg",
        trailer_key="abc123",
        awards={"oscar_wins": ["Best Picture"], "oscar_nominations": ["Best Director"]},
        streaming=[{"name": "Peacock"}],
    )
    segs = select_layout_segments("ENTITY_LOOKUP", [], tool_outputs, response)
    assert segs[0] == "MOVIE_CARD"
    assert "TRAILER_EMBED" in segs
    assert "AWARDS_CARD" in segs
    assert "STREAMING_STRIP" in segs
    # Trailer must come before awards and streaming
    assert segs.index("TRAILER_EMBED") < segs.index("AWARDS_CARD")
    assert segs.index("TRAILER_EMBED") < segs.index("STREAMING_STRIP")


def test_segments_analysis_poster_anchors_before_essay():
    """FILM_ANALYSIS + poster → MOVIE_CARD anchors before ANALYSIS_TEXT."""
    tool_outputs = {
        "tmdb": {"status": "success", "data": {}},
        "rag": {"status": "success", "data": {}},
    }
    response = _make_response(
        entity_type="movie",
        poster_url="https://example.com/poster.jpg",
    )
    segs = select_layout_segments("FILM_ANALYSIS", [], tool_outputs, response)
    assert "MOVIE_CARD" in segs
    assert "ANALYSIS_TEXT" in segs
    assert segs.index("MOVIE_CARD") < segs.index("ANALYSIS_TEXT")


def test_segments_disambiguation_wins_alone():
    """Any disambiguation status → only CLARIFICATION segment returned."""
    tool_outputs = {
        "tmdb": {"status": "disambiguation", "data": {}},
    }
    response = _make_response(entity_type="movie", poster_url="https://x.com/p.jpg")
    segs = select_layout_segments("ENTITY_LOOKUP", [], tool_outputs, response)
    assert segs == ["CLARIFICATION"]


def test_segments_person_card_hero():
    """entity_type=person → PERSON_CARD is the hero segment."""
    tool_outputs = {"tmdb": {"status": "success", "data": {}}}
    response = _make_response(entity_type="person", poster_url="https://x.com/p.jpg")
    segs = select_layout_segments("ENTITY_LOOKUP", [], tool_outputs, response)
    assert segs[0] == "PERSON_CARD"


def test_segments_no_trailer_for_recommendation_intent():
    """RECOMMENDATION intent must not embed trailer even if trailer_key is present."""
    tool_outputs = {"recommendation_engine": {"status": "success", "data": {}}}
    response = _make_response(
        entity_type="movie",
        poster_url="https://x.com/p.jpg",
        trailer_key="xyz",
        recommendations=[{"title": "Inception"}],
    )
    segs = select_layout_segments("RECOMMENDATION", [], tool_outputs, response)
    assert "TRAILER_EMBED" not in segs
