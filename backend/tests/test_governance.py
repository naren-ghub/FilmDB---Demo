from app.governance import filter_tool_calls


def test_filter_tool_calls_relevance_and_max():
    user_message = "Can you recommend movies like The Godfather and where to stream it?"
    tool_calls = [
        {"name": "imdb", "arguments": {"title": "The Godfather"}},
        {"name": "watchmode", "arguments": {"title": "The Godfather", "region": "US"}},
        {"name": "similarity", "arguments": {"title": "The Godfather"}},
        {"name": "archive", "arguments": {"title": "The Godfather"}},
    ]

    approved = filter_tool_calls(user_message, tool_calls, max_tools=3)
    names = [call["name"] for call in approved]

    assert "similarity" in names
    assert "watchmode" in names
    assert "archive" not in names
    assert len(approved) <= 3


def test_filter_tool_calls_invalid_name_skipped():
    user_message = "I want streaming info"
    tool_calls = [
        {"name": None, "arguments": {}},
        {"arguments": {"title": "Test"}},
        {"name": "watchmode", "arguments": {"title": "Test", "region": "US"}},
    ]

    approved = filter_tool_calls(user_message, tool_calls, max_tools=3)
    assert len(approved) == 1
    assert approved[0]["name"] == "watchmode"
