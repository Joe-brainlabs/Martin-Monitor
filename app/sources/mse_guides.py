"""MSE guide pages: fetch, strip to text, hash. When a page changes, store the diff as an event."""

import difflib

from .. import db
from .base import Item, fetch_page, inner, sha1, strip_html


def fetch(con, cfg: dict) -> list[Item]:
    items, failures = [], []
    for url in cfg["urls"]:
        try:
            page = fetch_page(url)
        except Exception as exc:
            failures.append(f"{url}: {exc}"[:200])
            continue
        title = strip_html(inner(page, "title") or "", limit=200) or url
        text = strip_html(inner(page, "main") or inner(page, "article") or page)
        digest = sha1(text)
        previous_hash = db.get_state(con, f"guide_hash:{url}")
        previous_text = db.get_state(con, f"guide_text:{url}") or ""
        if previous_hash and previous_hash != digest:
            diff = "\n".join(
                list(difflib.unified_diff(previous_text.splitlines(), text.splitlines(), lineterm="", n=1))[:200]
            )
            now = db.utcnow()
            items.append(
                Item(
                    source="mse_guides",
                    kind="guide_change",
                    external_id=f"{sha1(url)}:{now}",
                    author="MoneySavingExpert",
                    title=f"Guide updated: {title}",
                    text=diff[:8000],
                    url=url,
                    published_at=now,
                    metrics={"chars_before": len(previous_text), "chars_after": len(text)},
                )
            )
        db.set_state(con, f"guide_hash:{url}", digest)
        db.set_state(con, f"guide_text:{url}", text)
    db.set_state(con, "guide_failures", db.json.dumps(failures))
    if failures and len(failures) == len(cfg["urls"]):
        raise RuntimeError("every guide page failed: " + "; ".join(failures))
    return items
