"""National press pickup via Google News and Bing News RSS. No key, no vendor."""

import re

from .base import Item, http_get, parse_rss, sha1

GOOGLE = "https://news.google.com/rss/search"
BING = "https://www.bing.com/news/search"


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def fetch(con, cfg: dict) -> list[Item]:
    items: dict[str, Item] = {}
    for query in cfg["queries"]:
        feeds = [
            ("google_news", http_get(GOOGLE, params={"q": query, "hl": "en-GB", "gl": "GB", "ceid": "GB:en"}).text),
            ("bing_news", http_get(BING, params={"q": query, "format": "rss", "cc": "GB"}).text),
        ]
        for via, xml_text in feeds:
            for entry in parse_rss(xml_text):
                title = entry.get("title") or ""
                publisher = entry.get("source") or None
                if via == "google_news" and " - " in title:
                    title, _, publisher = title.rpartition(" - ")
                if not title:
                    continue
                key = sha1(_norm(title))
                if key in items:
                    continue
                items[key] = Item(
                    source="press",
                    kind="press",
                    external_id=key,
                    author=publisher,
                    title=title.strip(),
                    text=None,
                    url=entry.get("link"),
                    published_at=entry.get("published_at"),
                    metrics={"via": via, "query": query},
                    raw=entry,
                )
    return list(items.values())
