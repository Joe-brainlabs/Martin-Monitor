"""Queries shared by the API and Brian: activity ordering and the MSE/press pickup chain."""

import datetime as dt
import re

from . import db

# When an item was last active: a forum thread's latest comment, otherwise when it was published.
ACTIVITY = "COALESCE(json_extract(metrics_json, '$.last_comment_at'), published_at, first_seen_at)"



CHAIN_HOURS = 48  # how long after a Martin post we look for MSE and press pickup on the same topic


def attach_chains(con, items: list[dict]) -> None:
    """For Martin's own posts, count MSE and press items on a shared topic within CHAIN_HOURS afterwards."""
    martin = [i for i in items if i["source"] in ("x_martinslewis", "instagram") and i.get("topics") and i.get("published_at")]
    if not martin:
        return
    lo = min(i["published_at"] for i in martin)
    hi = (dt.datetime.fromisoformat(max(i["published_at"] for i in martin)) + dt.timedelta(hours=CHAIN_HOURS)).isoformat(timespec="seconds")
    followers = [
        db.row_to_item(r)
        for r in con.execute(
            """SELECT id, source, author, title, url, published_at, topics_json, metrics_json FROM items
               WHERE source IN ('mse_news', 'press', 'x_moneysavingexp') AND published_at BETWEEN ? AND ?""",
            (lo, hi),
        )
    ]
    for post in martin:
        start = dt.datetime.fromisoformat(post["published_at"])
        end = start + dt.timedelta(hours=CHAIN_HOURS)
        topics = set(post["topics"])
        hits = [
            f for f in followers
            if f.get("topics") and topics & set(f["topics"]) and start <= dt.datetime.fromisoformat(f["published_at"]) <= end
        ]
        if hits:
            post["chain"] = {
                "mse": [{"id": f["id"], "title": f["title"], "url": f["url"]} for f in hits if f["source"] in ("mse_news", "x_moneysavingexp")][:3],
                "press": [{"id": f["id"], "title": f["title"], "url": f["url"], "publisher": f["author"]} for f in hits if f["source"] == "press"][:6],
            }


# Cross-posts: Martin (and MSE) often put the same words on X and Instagram, sometimes YouTube. Posts from different
# sources within CROSSPOST_HOURS of each other whose text is essentially the same point at each other, so a card can say
# "also on Instagram" and Brian can count the reach across channels.
CROSSPOST_SOURCES = ("x_martinslewis", "instagram", "x_moneysavingexp", "youtube")
CROSSPOST_HOURS = 72
CROSSPOST_MIN_WORDS = 8     # shorter texts match by accident too easily
CROSSPOST_THRESHOLD = 0.6   # share of the shorter post's word pairs that must appear in the longer one
_WORD = re.compile(r"[a-z0-9£%']+")
_METRIC_KEYS = ("like_count", "retweet_count", "impression_count", "likes", "comments", "views")


def text_words(text: str | None) -> list[str]:
    """Lower-case words with links, handles and hashtags removed, so a tweet and its caption compare on the words alone."""
    t = (text or "").lower().replace("&amp;", " ").replace("\u2019", "'")
    t = re.sub(r"https?://\S+|www\.\S+", " ", t)
    t = re.sub(r"[@#]\w+", " ", t)
    return _WORD.findall(t)


def same_text(a: list[str], b: list[str]) -> bool:
    """True when the shorter post's word pairs mostly appear in the longer one. Survives truncation (an X post cut
    short, an Instagram caption with extra lines) better than comparing whole strings."""
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < CROSSPOST_MIN_WORDS:
        return False
    pairs = set(zip(short, short[1:]))
    return bool(pairs) and len(pairs & set(zip(long_, long_[1:]))) / len(pairs) >= CROSSPOST_THRESHOLD


def attach_crossposts(con, items: list[dict]) -> None:
    """For Martin's and MSE's own posts, list the posts on other channels that carry essentially the same text."""
    own = [i for i in items if i["source"] in CROSSPOST_SOURCES and i.get("published_at") and (i.get("text") or i.get("title"))]
    if not own:
        return
    span = dt.timedelta(hours=CROSSPOST_HOURS)
    lo = (dt.datetime.fromisoformat(min(i["published_at"] for i in own)) - span).isoformat(timespec="seconds")
    hi = (dt.datetime.fromisoformat(max(i["published_at"] for i in own)) + span).isoformat(timespec="seconds")
    marks = ",".join("?" * len(CROSSPOST_SOURCES))
    pool = [
        db.row_to_item(r)
        for r in con.execute(
            f"""SELECT id, source, title, text, url, published_at, metrics_json FROM items
                WHERE source IN ({marks}) AND published_at BETWEEN ? AND ?""",
            (*CROSSPOST_SOURCES, lo, hi),
        )
    ]
    words = {p["id"]: text_words(f"{p.get('title') or ''} {p.get('text') or ''}") for p in pool}
    for post in own:
        mine = words.get(post["id"]) or text_words(f"{post.get('title') or ''} {post.get('text') or ''}")
        when = dt.datetime.fromisoformat(post["published_at"])
        hits = [
            c for c in pool
            if c["id"] != post["id"] and c["source"] != post["source"]
            and abs(dt.datetime.fromisoformat(c["published_at"]) - when) <= span
            and same_text(mine, words[c["id"]])
        ]
        if hits:
            hits.sort(key=lambda c: c["published_at"])
            post["crossposts"] = [
                {"id": c["id"], "source": c["source"], "url": c["url"], "published_at": c["published_at"],
                 "metrics": {k: v for k, v in (c.get("metrics") or {}).items() if k in _METRIC_KEYS and v not in (None, "", 0)}}
                for c in hits[:3]
            ]
