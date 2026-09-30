"""Reddit via EnsembleData's subreddit endpoint (its keyword search endpoint does not exist).
We page through each subreddit's newest posts and keep those that mention Martin or MSE, or that
match a CTM topic. About two units a page; a few pages a day per subreddit."""

import datetime as dt

from .base import Item, http_get, mentions, tag_topics

API = "https://ensembledata.com/apis/reddit/subreddit/posts"


def fetch(con, cfg: dict) -> list[Item]:
    from ..config import env

    token = env("ENSEMBLE_TOKEN")
    mention_terms = [t.lower() for t in cfg.get("mention_terms", [])]
    items = []
    for subreddit in cfg["subreddits"]:
        cursor = None
        for _ in range(cfg.get("pages", 3)):
            params = {"name": subreddit, "sort": cfg.get("sort", "new"), "period": cfg.get("period", "day"), "token": token}
            if cursor:
                params["cursor"] = cursor
            data = http_get(API, params=params, timeout=60).json().get("data") or {}
            posts = data.get("posts") if isinstance(data, dict) else data
            for post in posts or []:
                p = post.get("data", post)
                blob = f"{p.get('title') or ''} {p.get('selftext') or ''}"
                mentioned = mentions(blob, mention_terms)
                topics = tag_topics(blob)
                if not mentioned and not topics:
                    continue
                created = p.get("created_utc")
                items.append(
                    Item(
                        source="reddit",
                        kind="thread",
                        external_id=str(p.get("id")),
                        author=f"u/{p.get('author')}" if p.get("author") else None,
                        title=p.get("title"),
                        text=(p.get("selftext") or "")[:10000] or None,
                        url=f"https://www.reddit.com{p.get('permalink')}" if p.get("permalink") else p.get("url"),
                        published_at=dt.datetime.fromtimestamp(float(created), dt.timezone.utc).isoformat(timespec="seconds") if created else None,
                        metrics={
                            "subreddit": p.get("subreddit") or subreddit,
                            "score": p.get("score", 0),
                            "comments": p.get("num_comments", 0),
                            "upvote_ratio": p.get("upvote_ratio"),
                            "mentions_martin": mentioned,
                        },
                        topics=topics,
                        raw={"flair": p.get("link_flair_text")},
                    )
                )
            cursor = data.get("nextCursor") if isinstance(data, dict) else None
            if not cursor or not posts:
                break
    return items
