"""Martin Lewis and MSE on X, via the X API v2 user timeline. Each tweet returned costs money, so
we fetch only what is new (since_id) and cap the very first run."""

import datetime as dt
import json
import time

from .. import db
from ..config import env
from .base import Item, http_get, to_iso

API = "https://api.x.com/2"
FIELDS = "created_at,public_metrics,conversation_id,in_reply_to_user_id,referenced_tweets,entities,lang"
CHECKPOINTS_H = (1, 6, 24)  # re-read public_metrics this long after posting; three reads a tweet, about 1.5p
COST_PER_TWEET = 0.005


def _get(path: str, params: dict) -> dict:
    token = env("BEARER_TOKEN")
    response = http_get(f"{API}{path}", params=params, headers={"Authorization": f"Bearer {token}"})
    return response.json()


def _user_id(con, handle: str) -> str:
    key = f"x_user_id:{handle.lower()}"
    cached = db.get_state(con, key)
    if cached:
        return cached
    user_id = _get(f"/users/by/username/{handle}", {})["data"]["id"]
    db.set_state(con, key, user_id)
    return user_id


def _tweet_item(handle: str, tweet: dict) -> Item:
    return Item(
        source=f"x_{handle.lower()}",
        kind="post",
        external_id=tweet["id"],
        author=f"@{handle}",
        text=tweet.get("text"),
        url=f"https://x.com/{handle}/status/{tweet['id']}",
        published_at=to_iso(tweet.get("created_at")),
        metrics=tweet.get("public_metrics", {}),
        raw=tweet,
    )


def refresh_metrics(con, cfg: dict) -> int:
    """Re-read public_metrics for recent tweets that have passed a checkpoint. Returns tweets read."""
    now = dt.datetime.now(dt.timezone.utc)
    due: dict[str, tuple[str, int]] = {}
    for account in cfg["handles"]:
        handle = account["handle"]
        rows = con.execute(
            "SELECT external_id, published_at FROM items WHERE source = ? AND published_at >= ?",
            (f"x_{handle.lower()}", (now - dt.timedelta(hours=CHECKPOINTS_H[-1] + 3)).isoformat(timespec="seconds")),
        ).fetchall()
        for row in rows:
            age_h = (now - dt.datetime.fromisoformat(row["published_at"])).total_seconds() / 3600
            done = json.loads(db.get_state(con, f"x_refresh:{row['external_id']}", "[]"))
            passed = [c for c in CHECKPOINTS_H if age_h >= c and c not in done]
            if passed:
                due[row["external_id"]] = (handle, max(passed))
    if not due:
        return 0
    ids = list(due)
    for start in range(0, len(ids), 100):
        batch = ids[start:start + 100]
        page = _get("/tweets", {"ids": ",".join(batch), "tweet.fields": FIELDS})
        by_handle: dict[str, list[Item]] = {}
        for tweet in page.get("data", []):
            handle, checkpoint = due[tweet["id"]]
            by_handle.setdefault(handle, []).append(_tweet_item(handle, tweet))
        for handle, items in by_handle.items():
            db.upsert_items(con, items)  # known ids: metrics are updated and a snapshot kept when they changed
        for tweet_id in batch:
            _, checkpoint = due[tweet_id]
            done = json.loads(db.get_state(con, f"x_refresh:{tweet_id}", "[]"))
            db.set_state(con, f"x_refresh:{tweet_id}", json.dumps(sorted(set(done) | {c for c in CHECKPOINTS_H if c <= checkpoint})))
    return len(ids)


def backfill(con, cfg: dict, handle: str, max_tweets: int, include_replies: bool = False) -> dict:
    """Fetch older tweets for one handle, walking back from the oldest one stored. Costs about $0.005 a tweet
    fetched. By default replies are excluded at the API, so every paid tweet is kept; include_replies keeps
    his own thread continuations but pays for replies to other people, which are then dropped."""
    account = next((a for a in cfg["handles"] if a["handle"].lower() == handle.lower()), None)
    if not account:
        raise ValueError(f"unknown handle {handle!r}")
    handle = account["handle"]
    source = f"x_{handle.lower()}"
    user_id = _user_id(con, handle)
    oldest = con.execute("SELECT MIN(CAST(external_id AS INTEGER)) AS m FROM items WHERE source = ?", (source,)).fetchone()["m"]
    params = {"tweet.fields": FIELDS, "exclude": "retweets" if include_replies else "retweets,replies", "max_results": 100}
    if oldest:
        params["until_id"] = str(oldest)
    fetched, stored, pages = 0, 0, 0
    while fetched < max_tweets and pages < 40:
        params["max_results"] = max(5, min(100, max_tweets - fetched))
        page = _get(f"/users/{user_id}/tweets", params)
        tweets = page.get("data", [])
        fetched += len(tweets)
        pages += 1
        keep = [t for t in tweets if not t.get("in_reply_to_user_id") or t["in_reply_to_user_id"] == user_id]
        stored += db.upsert_items(con, [_tweet_item(handle, t) for t in keep])
        next_token = page.get("meta", {}).get("next_token")
        if not tweets or not next_token:
            break
        params["pagination_token"] = next_token
    return {"handle": handle, "fetched": fetched, "stored": stored, "estimated_cost_usd": round(fetched * COST_PER_TWEET, 2)}


def fetch(con, cfg: dict) -> list[Item]:
    items: list[Item] = []
    for account in cfg["handles"]:
        handle = account["handle"]
        source = f"x_{handle.lower()}"
        user_id = _user_id(con, handle)
        since_id = db.latest_numeric_id(con, source)
        params = {"tweet.fields": FIELDS, "exclude": "retweets"}
        params["max_results"] = 100 if since_id else max(5, min(100, cfg.get("initial_max", 20)))
        if since_id:
            params["since_id"] = since_id
        pages = 0
        while True:
            try:
                page = _get(f"/users/{user_id}/tweets", params)
            except Exception as exc:  # 429: wait once for the window to reset, then give up for this run
                if "429" in str(exc) and pages == 0:
                    time.sleep(15)
                    page = _get(f"/users/{user_id}/tweets", params)
                else:
                    raise
            for tweet in page.get("data", []):
                reply_to = tweet.get("in_reply_to_user_id")
                if reply_to and reply_to != user_id:
                    continue  # keep his own threads, drop replies to other people
                items.append(_tweet_item(handle, tweet))
            pages += 1
            next_token = page.get("meta", {}).get("next_token")
            if not next_token or not since_id or pages >= 5:
                break  # first run: one page only; later runs: page through the new tweets
            params["pagination_token"] = next_token
    new = db.upsert_items(con, items)
    refresh_metrics(con, cfg)
    return new
