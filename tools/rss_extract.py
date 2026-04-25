#!/usr/bin/env python3
import sys
import re
import html
import xml.etree.ElementTree as ET

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")

def clean_text(s: str) -> str:
    if not s:
        return ""
    s = html.unescape(s)
    s = TAG_RE.sub(" ", s)
    s = WS_RE.sub(" ", s).strip()
    # Remove trailing Guardian boilerplate
    s = re.sub(r"\s*Continue reading\.\.\.\s*$", "", s)
    return s

def first_text(elem, paths):
    for p in paths:
        x = elem.find(p)
        if x is not None and x.text:
            t = x.text.strip()
            if t:
                return t
    return ""

def main() -> int:
    data = sys.stdin.read()
    if not data.strip():
        return 2

    try:
        root = ET.fromstring(data)
    except Exception:
        # If malformed XML, fail deterministically
        return 2

    # RSS: <channel><item>...
    items = root.findall(".//item")
    if items:
        for it in items:
            title = clean_text(first_text(it, ["title"]))
            pub = clean_text(first_text(it, ["pubDate"]))
            desc = clean_text(first_text(it, ["description"]))
            if title:
                print(f"TITLE: {title}")
            if pub:
                print(f"DATE: {pub}")
            if desc:
                print(f"DESC: {desc}")
            print("")
        return 0

    # Atom: <entry>...
    entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    if entries:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for en in entries:
            title = clean_text(first_text(en, ["a:title", "{http://www.w3.org/2005/Atom}title"]))
            upd = clean_text(first_text(en, ["a:updated", "{http://www.w3.org/2005/Atom}updated"]))
            summ = clean_text(first_text(en, ["a:summary", "{http://www.w3.org/2005/Atom}summary"]))
            if title:
                print(f"TITLE: {title}")
            if upd:
                print(f"DATE: {upd}")
            if summ:
                print(f"DESC: {summ}")
            print("")
        return 0

    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        # Consumer closed pipe early (e.g., head). Exit cleanly.
        try:
            sys.stdout.close()
        except Exception:
            pass
        sys.exit(0)
