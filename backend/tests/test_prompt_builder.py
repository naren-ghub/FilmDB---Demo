from app.utils.prompt_builder import build_prompt


def test_build_prompt_sections():
    system, user, context = build_prompt(
        system_instructions="You are FilmDB",
        user_profile={"region": "US"},
        recent_messages=[{"role": "user", "content": "Hi"}],
        tool_summaries=["imdb: ok"],
        user_query="Tell me about Inception",
    )

    assert "FilmDB" in system
    assert "region" in system  # profile goes into system
    assert len(context) == 1  # one history message
    assert context[0]["role"] == "user"
    assert "Inception" in user
    assert "REFERENCE DATA" in user  # tool data present
