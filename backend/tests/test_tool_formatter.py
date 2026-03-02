from app.utils.tool_formatter import normalize_tool_output, summarize_tool_data


def test_normalize_tool_output_status():
    output = normalize_tool_output("weird", {"a": 1})
    assert output["status"] == "error"


def test_summarize_tool_data_imdb():
    output = {"status": "success", "data": {"title": "Test", "year": 2000, "rating": 7.1}}
    summary = summarize_tool_data("imdb", output)
    assert "Test" in summary
    assert "2000" in summary
