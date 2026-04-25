import re
from html import unescape
from html.parser import HTMLParser

SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style)\b.*?>.*?</\1>")

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        s = data.strip()
        if s:
            self.parts.append(s)

def html_to_text(html: str) -> str:
    html = SCRIPT_STYLE_RE.sub(" ", html)
    html = re.sub(r"(?is)<!--.*?-->", " ", html)
    html = re.sub(r"(?is)<noscript\b.*?>.*?</noscript>", " ", html)
    p = TextExtractor()
    p.feed(html)
    text = "\n".join(p.parts)
    text = unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text
