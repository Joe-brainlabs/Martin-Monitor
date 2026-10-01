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

from ..config import BROWSER_UA, SOURCES, env

DECODO_ENDPOINT = "https://scraper-api.decodo.com/v2/scrape"


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


def decodo_page(url: str) -> str:
    """HTML for a URL through Decodo's Web Scraping API (universal target, residential IPs)."""
    response = httpx.post(
        DECODO_ENDPOINT,
        json={"target": "universal", "url": url},
        auth=(env("DECODO_USERNAME"), env("DECODO_PASSWORD")),
        headers={"User-Agent": BROWSER_UA},
        timeout=120,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Decodo returned HTTP {response.status_code} for {url}: {response.text[:120]}")
    content = response.json()["results"][0]["content"]
    return content if isinstance(content, str) else json.dumps(content)


def fetch_page(url: str) -> str:
    """HTML for a page. Direct first; MSE's Cloudflare refuses datacentre IPs (Railway) with a 403,
    so on 403 we go through Decodo when its credentials are present."""
    try:
        return http_get(url).text
    except RuntimeError as exc:
        if "HTTP 403" not in str(exc) or not (env("DECODO_USERNAME") and env("DECODO_PASSWORD")):
            raise
    return decodo_page(url)


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


_TOPIC_PATTERNS = {
    topic: re.compile(r"\b(?:" + "|".join(re.escape(p.lower()) for p in phrases) + r")(?:e?s)?\b")
    for topic, phrases in SOURCES["topics"].items()
}


def tag_topics(text: str) -> list[str]:
    """CTM sub-brands whose keyword phrases appear as whole words in the text (case-insensitive, plurals allowed)."""
    lowered = text.lower()
    return [topic for topic, pattern in _TOPIC_PATTERNS.items() if pattern.search(lowered)]


TOPICS_VERSION = "2026-10-01-subbrands"
RENAMED = {"car_insurance": "car", "home_insurance": "home", "pet_insurance": "pet", "travel_insurance": "travel"}


def retag_all(con) -> int:
    """Recompute keyword categories on every stored item, and rename old keys inside Brian's views.
    Runs once per TOPICS_VERSION, at start-up."""
    from .. import db

    if db.get_state(con, "topics_version") == TOPICS_VERSION:
        return 0
    rows = con.execute("SELECT id, source, title, text, brian_json FROM items").fetchall()
    for r in rows:
        topics = tag_topics(f"{r['title'] or ''} {r['text'] or ''}") if r["source"] != "reddit" else None
        brian = r["brian_json"]
        if brian:
            view = json.loads(brian)
            view["topics"] = [RENAMED.get(t, t) for t in view.get("topics", [])]
            for impact in view.get("impact", []):
                impact["product"] = RENAMED.get(impact.get("product"), impact.get("product"))
            brian = json.dumps(view)
        if topics is None:  # Reddit items keep their tags but get the new keys
            old = con.execute("SELECT topics_json FROM items WHERE id = ?", (r["id"],)).fetchone()["topics_json"]
            topics = [RENAMED.get(t, t) for t in json.loads(old or "[]")]
            topics = sorted(set(topics) | set(tag_topics(f"{r['title'] or ''} {r['text'] or ''}")), key=list(SOURCES["topics"]).index)
        con.execute("UPDATE items SET topics_json = ?, brian_json = ? WHERE id = ?", (json.dumps(topics), brian, r["id"]))
    insights = con.execute("SELECT id, impact_json FROM insights").fetchall()
    for r in insights:
        impacts = json.loads(r["impact_json"] or "[]")
        for impact in impacts:
            impact["product"] = RENAMED.get(impact.get("product"), impact.get("product"))
        con.execute("UPDATE insights SET impact_json = ? WHERE id = ?", (json.dumps(impacts), r["id"]))
    con.commit()
    db.set_state(con, "topics_version", TOPICS_VERSION)
    return len(rows)


def mentions(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return any(re.search(r"\b" + re.escape(t.lower()) + r"\b", lowered) for t in terms)


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()
