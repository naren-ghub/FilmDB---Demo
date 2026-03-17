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

    # Escape raw HTML first.
    raw = _html.escape(text)

    # Code fences first to avoid accidental formatting inside.
    raw = re.sub(
        r"```(\w+)?\n([\s\S]*?)```",
        lambda m: f"<pre><code class='lang-{(m.group(1) or '').strip()}'>{m.group(2).strip()}</code></pre>",
        raw,
    )

    # Horizontal rules.
    raw = re.sub(r"^\s*---+\s*$", "<hr>", raw, flags=re.MULTILINE)

    # Headings (# to ### only, mapped to h3-h5).
    raw = re.sub(r"^### (.+)$", r"<h5>\1</h5>", raw, flags=re.MULTILINE)
    raw = re.sub(r"^## (.+)$", r"<h4>\1</h4>", raw, flags=re.MULTILINE)
    raw = re.sub(r"^# (.+)$", r"<h3>\1</h3>", raw, flags=re.MULTILINE)

    # Blockquotes.
    raw = re.sub(
        r"^&gt;\s?(.+)$",
        r"<blockquote>\1</blockquote>",
        raw,
        flags=re.MULTILINE,
    )

    # Links.
    raw = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        raw,
    )

    # Emphasis.
    raw = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", raw)
    raw = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", raw)
    raw = re.sub(r"\*(.+?)\*", r"<em>\1</em>", raw)

    # Inline code.
    raw = re.sub(r"`([^`]+)`", r"<code>\1</code>", raw)

    # Lists.
    raw = re.sub(r"^\s*[\-\*]\s+(.+)$", r"<li>\1</li>", raw, flags=re.MULTILINE)
    raw = re.sub(r"^\s*\d+\.\s+(.+)$", r"<li>\1</li>", raw, flags=re.MULTILINE)
    raw = re.sub(r"((?:<li>.+?</li>\n?)+)", r"<ul>\1</ul>", raw)

    # Simple pipe table support.
    lines = raw.splitlines()
    rendered: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if "|" in line and i + 1 < len(lines):
            sep = lines[i + 1].strip()
            if re.match(r"^\s*\|?[-:\s|]+\|?\s*$", sep):
                headers = [c.strip() for c in line.strip().strip("|").split("|")]
                rows: list[list[str]] = []
                i += 2
                while i < len(lines) and "|" in lines[i]:
                    rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                    i += 1
                thead = "".join(f"<th>{h}</th>" for h in headers)
                body_rows = []
                for row in rows:
                    cells = "".join(f"<td>{c}</td>" for c in row)
                    body_rows.append(f"<tr>{cells}</tr>")
                rendered.append(
                    "<table><thead><tr>"
                    + thead
                    + "</tr></thead><tbody>"
                    + "".join(body_rows)
                    + "</tbody></table>"
                )
                continue
        rendered.append(line)
        i += 1
    raw = "\n".join(rendered)

    # Paragraphs.
    raw = re.sub(r"\n{2,}", "</p><p>", raw)
    raw = raw.replace("\n", "<br>")
    return f"<p>{raw}</p>"
