"""HTML/RSS/text article extraction and numeric-token fact preservation for News Studio."""
from __future__ import annotations

import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from videocreator.autopilot import parse_rss_or_atom_items
from videocreator.tts.syllables import count_syllables, max_syllables_for_duration

VALID_NEWS_SOURCE_KINDS: frozenset[str] = frozenset({"url", "rss", "raw_text"})
_NUM_TOKEN_RE = re.compile(r"\b\d+(?:[.,:/-]\d+)*(?:%|\b)")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\r?\n+")


class _ArticleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._in_title = False
        self._in_h1 = False
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.body_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in ("script", "style", "noscript", "nav", "footer", "aside"):
            self._skip_depth += 1
        elif t == "title":
            self._in_title = True
        elif t == "h1":
            self._in_h1 = True

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in ("script", "style", "noscript", "nav", "footer", "aside") and self._skip_depth > 0:
            self._skip_depth -= 1
        elif t == "title":
            self._in_title = False
        elif t == "h1":
            self._in_h1 = False
        elif t in ("p", "li", "h2", "h3", "article", "section", "div") and self._skip_depth == 0:
            self.body_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        if self._in_title:
            self.title_parts.append(cleaned)
        if self._in_h1:
            self.h1_parts.append(cleaned)
        self.body_parts.append(cleaned + " ")


def _read_url_bytes(url_or_path: str) -> bytes:
    raw = (url_or_path or "").strip()
    if raw.lower().startswith("file://"):
        parsed = urlsplit(raw)
        local = Path(urllib.request.url2pathname(parsed.path))
        return local.read_bytes()
    if Path(raw).is_file():
        return Path(raw).read_bytes()
    req = urllib.request.Request(raw, headers={"User-Agent": "VideoCreator/2.0"})
    with urllib.request.urlopen(req, timeout=20.0) as resp:
        return resp.read()


def extract_article_facts(
    source_kind: str,
    *,
    source_url: str = "",
    raw_text: str = "",
) -> dict[str, Any]:
    """Extracts headline, factual sentences, and preserved numeric/date tokens from URL HTML, RSS, or raw text."""
    kind = (source_kind or "raw_text").strip().lower()
    if kind not in VALID_NEWS_SOURCE_KINDS:
        raise ValueError(f"Unsupported news source_kind '{source_kind}'")

    headline = ""
    full_text = ""
    if kind == "raw_text":
        full_text = (raw_text or "").strip()
        lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]
        headline = lines[0] if lines else "Tin mới hôm nay"
    elif kind == "rss":
        items = parse_rss_or_atom_items(source_url)
        if not items:
            raise ValueError("RSS feed returned no parseable items")
        first = items[0]
        headline = first["title"]
        full_text = f"{first['title']}. {first['summary']}".strip()
    else:  # url HTML
        html_str = _read_url_bytes(source_url).decode("utf-8", errors="replace")
        parser = _ArticleHTMLParser()
        parser.feed(html_str)
        headline = (" ".join(parser.h1_parts).strip() or " ".join(parser.title_parts).strip())
        full_text = " ".join("".join(parser.body_parts).split()).strip()
        if not headline and full_text:
            headline = full_text[:80]

    if not full_text:
        raise ValueError("Article source produced empty text")

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(full_text) if len(s.strip()) >= 8]
    if not sentences:
        sentences = [full_text]

    seen_toks: list[str] = []
    for tok in _NUM_TOKEN_RE.findall(f"{headline} {full_text}"):
        if tok not in seen_toks:
            seen_toks.append(tok)

    domain = urlsplit(source_url).netloc if source_url.startswith(("http://", "https://")) else "local"
    return {
        "headline": headline[:140],
        "sentences": sentences[:10],
        "preserved_tokens": seen_toks[:8],
        "source_domain": domain or "local",
        "source_url": source_url,
    }


def fit_news_line(text: str, lang: str, duration_s: float) -> str:
    budget = max(4, max_syllables_for_duration(duration_s, lang))
    words = " ".join((text or "").split()).split()
    kept: list[str] = []
    for w in words:
        cand = " ".join([*kept, w])
        if count_syllables(cand, lang) > budget and kept:
            break
        kept.append(w)
    return " ".join(kept) or text[:40]


__all__ = [
    "VALID_NEWS_SOURCE_KINDS",
    "extract_article_facts",
    "fit_news_line",
]
