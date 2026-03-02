import pytest

from app.conversation_engine import ConversationEngine


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
