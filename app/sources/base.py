"""Shared bits for source modules: the Item shape, HTTP, RSS parsing, HTML stripping, topic tagging."""

import datetime as dt
import email.utils
import hashlib
import html
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from xml.etree import ElementTree

import httpx

from ..config import BROWSER_UA, SOURCES


@dataclass
class Item:
    source: str
    kind: str
    external_id: str
    author: str | None = None
    title: str | None = None
    text: str | None = None
    url: str | None = None
    published_at: str | None = None
    metrics: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
    topics: list[str] | None = None

    def to_row(self, first_seen_at: str) -> dict:
        topics = self.topics if self.topics is not None else tag_topics(f"{self.title or ''} {self.text or ''}")
        return {
            "source": self.source,
            "kind": self.kind,
            "external_id": str(self.external_id),
            "author": self.author,
            "title": self.title,
            "text": self.text,
            "url": self.url,
            "published_at": self.published_at,
            "first_seen_at": first_seen_at,
            "metrics_json": json.dumps(self.metrics, sort_keys=True) if self.metrics else None,
            "topics_json": json.dumps(topics),
            "raw_json": json.dumps(self.raw, ensure_ascii=False) if self.raw else None,
        }


def http_get(url: str, params: dict | None = None, headers: dict | None = None, timeout: float = 30) -> httpx.Response:
    merged = {"User-Agent": BROWSER_UA, "Accept-Language": "en-GB,en;q=0.9"}
    merged.update(headers or {})
    response = httpx.get(url, params=params, headers=merged, timeout=timeout, follow_redirects=True)
    if response.status_code >= 400:
        # Query strings can carry API keys (YouTube, Ensemble). Report the status and path only.
        ctype = response.headers.get("content-type", "")
        detail = f": {response.text[:200]}" if ("json" in ctype or "text/plain" in ctype) else ""
        raise RuntimeError(f"HTTP {response.status_code} from {response.url.copy_with(query=None)}{detail}")
    return response


def to_iso(value: str | None) -> str | None:
    """RFC 2822 or ISO 8601 in, UTC ISO 8601 out."""
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).isoformat(timespec="seconds")


def parse_rss(xml_text: str) -> list[dict]:
    """RSS 2.0 items as dicts: title, link, guid, published_at, description, source."""
    root = ElementTree.fromstring(xml_text)
    out = []
    for node in root.iter("item"):
        entry: dict = {}
        for child in node:
            tag = child.tag.split("}")[-1].lower()
            if tag in ("title", "link", "guid", "description"):
                entry[tag] = (child.text or "").strip()
            elif tag == "pubdate":
                entry["published_at"] = to_iso((child.text or "").strip())
            elif tag == "source":
                entry["source"] = (child.text or "").strip() or child.get("url", "")
        out.append(entry)
    return out


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "header", "footer"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        elif tag in ("p", "br", "li", "h1", "h2", "h3", "h4", "tr", "div"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)


def strip_html(fragment: str | None, limit: int | None = None) -> str:
    """Visible text from HTML, whitespace collapsed. Skips scripts, styles, nav, header and footer."""
    if not fragment:
        return ""
    parser = _Text()
    parser.feed(fragment)
    text = html.unescape("".join(parser.parts))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text).strip()
    return text[:limit] if limit else text


def inner(fragment: str, tag: str) -> str | None:
    """Contents of the first <tag> ... </tag> block, or None."""
    match = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", fragment, re.S | re.I)
    return match.group(1) if match else None


def meta_content(fragment: str, name: str) -> str | None:
    match = re.search(
        rf'<meta[^>]+(?:property|name)=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']*)["\']', fragment, re.I
    ) or re.search(
        rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']{re.escape(name)}["\']', fragment, re.I
    )
    return html.unescape(match.group(1)) if match else None


def tag_topics(text: str) -> list[str]:
    lowered = text.lower()
    return [topic for topic, phrases in SOURCES["topics"].items() if any(p.lower() in lowered for p in phrases)]


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()
