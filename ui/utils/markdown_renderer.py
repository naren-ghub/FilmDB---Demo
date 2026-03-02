"""
FilmDB – Markdown Renderer Utility
====================================
Converts markdown text to safe HTML for display inside bubbles.
Falls back to plain text when markdown is not available.
"""

import re
import html as _html


def md_to_html(text: str) -> str:
    """
    Lightweight markdown → HTML converter for assistant bubbles.
    Handles headings, bold, italic, inline code, unordered lists,
    ordered lists, links, and paragraphs.
    """
    if not text:
        return ""

    # Escape raw HTML first
    text = _html.escape(text)

    # Headings  (### → <h4>, ## → <h3>, # → <h2>)
    text = re.sub(r"^### (.+)$", r"<h5>\1</h5>", text, flags=re.MULTILINE)
    text = re.sub(r"^## (.+)$",  r"<h4>\1</h4>", text, flags=re.MULTILINE)
    text = re.sub(r"^# (.+)$",   r"<h3>\1</h3>", text, flags=re.MULTILINE)

    # Bold + italic
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)

    # Inline code
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

    # Links  [text](url)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        text,
    )

    # Unordered list items  (- or *)
    text = re.sub(r"^[\-\*]\s+(.+)$", r"<li>\1</li>", text, flags=re.MULTILINE)

    # Ordered list items  (1. 2. …)
    text = re.sub(r"^\d+\.\s+(.+)$", r"<li>\1</li>", text, flags=re.MULTILINE)

    # Wrap consecutive <li> in <ul>
    text = re.sub(
        r"((?:<li>.+?</li>\n?)+)",
        r"<ul>\1</ul>",
        text,
    )

    # Paragraphs – double newlines
    text = re.sub(r"\n{2,}", "</p><p>", text)
    # Single newlines → <br>
    text = text.replace("\n", "<br>")

    return f"<p>{text}</p>"
