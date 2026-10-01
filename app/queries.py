"""Queries shared by the API and Brian: activity ordering and the MSE/press pickup chain."""

import datetime as dt

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


