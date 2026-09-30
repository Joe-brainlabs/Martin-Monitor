"""Martin Lewis and MSE on X, via the X API v2 user timeline. Each tweet returned costs money, so
we fetch only what is new (since_id) and cap the very first run."""

import time

from .. import db
from ..config import env
from .base import Item, http_get, to_iso

API = "https://api.x.com/2"
FIELDS = "created_at,public_metrics,conversation_id,in_reply_to_user_id,referenced_tweets,entities,lang"


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
                items.append(
                    Item(
                        source=source,
                        kind="post",
                        external_id=tweet["id"],
                        author=f"@{handle}",
                        text=tweet.get("text"),
                        url=f"https://x.com/{handle}/status/{tweet['id']}",
                        published_at=to_iso(tweet.get("created_at")),
                        metrics=tweet.get("public_metrics", {}),
                        raw=tweet,
                    )
                )
            pages += 1
            next_token = page.get("meta", {}).get("next_token")
            if not next_token or not since_id or pages >= 5:
                break  # first run: one page only; later runs: page through the new tweets
            params["pagination_token"] = next_token
    return items
