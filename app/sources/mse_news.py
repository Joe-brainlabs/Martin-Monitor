"""MSE news: the RSS feed gives title, link and date; we fetch each new article once for its text."""

from .. import db
from .base import Item, http_get, inner, meta_content, parse_rss, strip_html


def fetch(con, cfg: dict) -> list[Item]:
    entries = parse_rss(http_get(cfg["feed"]).text)
    known = db.existing_ids(con, "mse_news")
    items = []
    for entry in entries:
        link = entry.get("link") or entry.get("guid")
        if not link or link in known:
            continue
        text, description = None, None
        try:
            page = http_get(link).text
            description = meta_content(page, "og:description") or meta_content(page, "description")
            body = inner(page, "article") or inner(page, "main") or page
            text = strip_html(body, limit=8000)
        except Exception as exc:  # keep the headline even if the article fetch is refused
            text = f"(article fetch failed: {type(exc).__name__})"
        items.append(
            Item(
                source="mse_news",
                kind="article",
                external_id=link,
                author="MoneySavingExpert",
                title=entry.get("title"),
                text=text,
                url=link,
                published_at=entry.get("published_at"),
                metrics={"description": description} if description else {},
                raw=entry,
            )
        )
    return items
