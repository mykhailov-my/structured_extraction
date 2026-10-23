"""HTML fragments as plain-text lines."""

from bs4 import Tag

_BLOCKS = ["p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "blockquote"]


def rich_lines(node: Tag) -> list[str]:
    """Text with its line structure: paragraphs and breaks become lines, list items '- '.
    Changes `node` in place."""
    for line_break in node.find_all("br"):
        line_break.replace_with("\n")
    for item in node.find_all("li"):
        item.insert(0, "- ")
    for block in node.find_all(_BLOCKS):
        block.append("\n")
    lines = (" ".join(line.split()) for line in node.get_text().splitlines())
    return [line for line in lines if line]


def fragment_lines(node: Tag) -> list[str]:
    """One line per text fragment, whitespace collapsed."""
    return [" ".join(text.split()) for text in node.stripped_strings]


def one_line(node: Tag | None) -> str:
    return " ".join(node.get_text(" ").split()) if node else ""
