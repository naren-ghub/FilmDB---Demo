from app.utils.prompt_builder import build_prompt


def test_build_prompt_sections():
    prompt = build_prompt(
        system_instructions="You are FilmDB",
        user_profile={"region": "US"},
        recent_messages=[{"role": "user", "content": "Hi"}],
        tool_summaries=["imdb: ok"],
        user_query="Tell me about Inception",
    )

    assert "SYSTEM:" in prompt
    assert "USER PROFILE:" in prompt
    assert "RECENT CONVERSATION:" in prompt
    assert "TOOL DATA:" in prompt
    assert "USER QUERY:" in prompt
