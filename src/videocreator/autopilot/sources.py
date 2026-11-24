"""RSS 2.0 / Atom XML feed and HTML text helpers for Channel Autopilot & News Studio."""
from __future__ import annotations

import hashlib
import html
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(raw: str) -> str:
    txt = html.unescape(raw or "")
    txt = _TAG_RE.sub(" ", txt)
    return " ".join(txt.split()).strip()


def _local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1].lower() if tag else ""


def parse_rss_or_atom_items(feed_url_or_path: str) -> list[dict[str, str]]:
    """Parse RSS 2.0 or Atom XML from HTTP URL, `file://` URI, or local XML file path."""
    raw_src = (feed_url_or_path or "").strip()
    if not raw_src:
        return []

    xml_bytes: bytes
    if raw_src.lower().startswith("file://"):
        parsed_uri = urlsplit(raw_src)
        local_path = Path(urllib.request.url2pathname(parsed_uri.path))
        xml_bytes = local_path.read_bytes()
    elif Path(raw_src).is_file():
        xml_bytes = Path(raw_src).read_bytes()
    else:
        req = urllib.request.Request(raw_src, headers={"User-Agent": "VideoCreator/2.0"})
        with urllib.request.urlopen(req, timeout=20.0) as resp:
            xml_bytes = resp.read()

    root = ET.fromstring(xml_bytes)
    items: list[dict[str, str]] = []
    for elem in root.iter():
        ltag = _local_tag(elem.tag)
        if ltag not in ("item", "entry"):
            continue
        title = ""
        summary = ""
        link = ""
        guid = ""
        for child in elem:
            ctag = _local_tag(child.tag)
            ctext = (child.text or "").strip()
            if ctag == "title" and not title:
                title = strip_html(ctext)
            elif ctag in ("description", "summary", "content") and not summary:
                summary = strip_html(ctext)
            elif ctag == "guid" and not guid:
                guid = ctext
            elif ctag == "id" and not guid:
                guid = ctext
            elif ctag == "link" and not link:
                href = str(child.attrib.get("href") or "").strip()
                link = href or ctext

        ident = guid or link or title
        if not ident:
            continue
        key_hash = hashlib.sha1(ident.encode("utf-8")).hexdigest()[:12]
        items.append(
            {
                "source_key": f"rss:{key_hash}",
                "title": title or link or ident,
                "summary": summary,
                "link": link,
            }
        )
    return items
