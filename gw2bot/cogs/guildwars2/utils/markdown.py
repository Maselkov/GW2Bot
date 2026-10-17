"""Convert forum HTML (game update notes) to Discord markdown."""
import re

from bs4 import BeautifulSoup, NavigableString

from .chat import en_space

BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li"}
SKIP_TAGS = {"img", "script", "style"}
INLINE_STYLES = {
    "strong": "**",
    "b": "**",
    "em": "*",
    "i": "*",
    "u": "__",
    "s": "~~",
    "strike": "~~",
    "del": "~~",
}
BULLETS = ["•", "◦"]
MARKDOWN_CHARS = re.compile(r"([\\*_~`|])")


def html_to_markdown(html):
    soup = BeautifulSoup(html, "html.parser")
    text = _render_children(soup, depth=0)
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _render_children(node, depth):
    return "".join(_render(child, depth) for child in node.children)


def _render(node, depth):
    if isinstance(node, NavigableString):
        if node.__class__ is not NavigableString:
            # Comments, CDATA, doctypes
            return ""
        text = re.sub(r"\s+", " ", str(node))
        return MARKDOWN_CHARS.sub(r"\\\1", text)
    name = node.name
    if name in SKIP_TAGS:
        return ""
    if name == "br":
        return "\n"
    if name in INLINE_STYLES:
        return _wrap(_render_children(node, depth), INLINE_STYLES[name])
    if name == "a":
        return _link(node, depth)
    if name in ("ul", "ol"):
        return "\n" + _list(node, depth) + "\n"
    if name in BLOCK_TAGS:
        content = _inline(_render_children(node, depth))
        if not content:
            return ""
        if name == "h1":
            content = _wrap(content, "**")
        elif name.startswith("h"):
            content = _wrap(content, "*")
        return "\n\n" + content + "\n\n"
    return _render_children(node, depth)


def _inline(text):
    """Tidy a block's content: no blank lines, no padding."""
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def _wrap(text, marker):
    """Wrap text in a markdown marker, keeping surrounding spaces outside.

    `**word **` doesn't render as bold in Discord.
    """
    stripped = text.strip()
    if not stripped:
        return text
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    return f"{lead}{marker}{stripped}{marker}{trail}"


def _link(node, depth):
    text = _render_children(node, depth).strip()
    href = (node.get("href") or "").strip()
    if href.startswith("mailto:"):
        return text or href[len("mailto:"):]
    if not href.startswith(("http://", "https://")):
        return text
    if not text:
        return f"<{href}>"
    return f"[{text}]({href})"


def _list(node, depth):
    bullet = BULLETS[min(depth, len(BULLETS) - 1)]
    indent = en_space * 2 * depth
    items = []
    for number, item in enumerate(node.find_all("li", recursive=False), start=1):
        marker = f"{number}." if node.name == "ol" else bullet
        nested = [child for child in item.children if getattr(child, "name", None) in ("ul", "ol")]
        for child in nested:
            child.extract()
        text = _inline(_render_children(item, depth))
        line = f"{indent}{marker} {text}" if text else ""
        sublists = [_list(child, depth + 1) for child in nested]
        items.append("\n".join(part for part in [line, *sublists] if part))
    return "\n".join(item for item in items if item)
