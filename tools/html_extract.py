#!/usr/bin/env python3
import sys
import re
from html.parser import HTMLParser
from html import unescape

class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out = []
        self._skip = 0  # script/style/noscript
    def handle_starttag(self, tag, attrs):
        t = tag.lower()
        if t in ("script","style","noscript"):
            self._skip += 1
        if t in ("p","br","div","li","tr","h1","h2","h3","h4","h5","h6"):
            self.out.append("\n")
    def handle_endtag(self, tag):
        t = tag.lower()
        if t in ("script","style","noscript") and self._skip > 0:
            self._skip -= 1
        if t in ("p","div","li","tr","h1","h2","h3","h4","h5","h6"):
            self.out.append("\n")
    def handle_data(self, data):
        if self._skip:
            return
        self.out.append(data)
    def handle_entityref(self, name):
        if self._skip:
            return
        self.out.append("&%s;" % name)
    def handle_charref(self, name):
        if self._skip:
            return
        self.out.append("&#%s;" % name)

html = sys.stdin.read()
p = Text()
p.feed(html)
txt = unescape("".join(p.out))
txt = re.sub(r"[ \t\r\f\v]+", " ", txt)
txt = re.sub(r"\n[ \t]+", "\n", txt)
txt = re.sub(r"\n{3,}", "\n\n", txt).strip()
sys.stdout.write(txt + ("\n" if txt else ""))
