"""Martin Lewis on Instagram via EnsembleData, the vendor Cortex's Social Comment Analyser already uses.
One unit buys ten posts and the trial allows 50 units a day, so hourly polling fits."""

import datetime as dt

from .. import db
from ..config import env
from .base import Item, http_get

API = "https://ensembledata.com/apis/instagram"


def _get(path: str, params: dict) -> dict:
    return http_get(f"{API}{path}", params={**params, "token": env("ENSEMBLE_TOKEN")}, timeout=60).json()


def _user_id(con, username: str) -> str:
    key = f"ig_user_id:{username.lower()}"
    cached = db.get_state(con, key)
    if cached:
        return cached
    info = _get("/user/info", {"username": username})["data"]
    user_id = str(info.get("pk") or info.get("id"))
    db.set_state(con, key, user_id)
    return user_id


def _caption(node: dict) -> str | None:
    caption = node.get("caption")
    if isinstance(caption, dict):
        return caption.get("text")
    if isinstance(caption, str):
        return caption
    edges = (node.get("edge_media_to_caption") or {}).get("edges") or []
    return edges[0]["node"]["text"] if edges else None


def _count(node: dict, *keys: str) -> int | None:
    for key in keys:
        value = node.get(key)
        if isinstance(value, dict):
            value = value.get("count")
        if value is not None:
            return int(value)
    return None


def backfill(con, cfg: dict, posts: int) -> dict:
    """Pull older posts: depth chunks of chunk_size, one unit per chunk."""
    chunk = cfg.get("chunk_size", 10)
    depth = max(1, -(-posts // chunk))
    items = fetch(con, {**cfg, "depth": depth})
    stored = db.upsert_items(con, items)
    return {"requested": posts, "fetched": len(items), "stored": stored, "units_used": depth}


def fetch(con, cfg: dict) -> list[Item]:
    items = []
    for account in cfg["accounts"]:
        username = account["username"]
        user_id = _user_id(con, username)
        data = _get("/user/posts", {"user_id": user_id, "depth": cfg.get("depth", 1), "chunk_size": cfg.get("chunk_size", 10)})["data"]
        posts = data.get("posts") if isinstance(data, dict) else data
        for post in posts or []:
            node = post.get("node", post)
            code = node.get("code") or node.get("shortcode")
            taken = node.get("taken_at") or node.get("taken_at_timestamp")
            published = dt.datetime.fromtimestamp(int(taken), dt.timezone.utc).isoformat(timespec="seconds") if taken else None
            thumb = node.get("display_url") or ((node.get("image_versions2") or {}).get("candidates") or [{}])[0].get("url")
            items.append(
                Item(
                    source="instagram",
                    kind="post",
                    external_id=str(node.get("pk") or node.get("id") or code),
                    author=f"@{username}",
                    text=_caption(node),
                    url=f"https://www.instagram.com/p/{code}/" if code else None,
                    published_at=published,
                    metrics={
                        "likes": _count(node, "like_count", "edge_liked_by", "edge_media_preview_like"),
                        "comments": _count(node, "comment_count", "edge_media_to_comment"),
                        "views": _count(node, "play_count", "view_count", "video_view_count"),
                        "media_type": node.get("media_type") or ("video" if node.get("is_video") else "image"),
                    },
                    raw={"code": code, "thumbnail": thumb},
                )
            )
    return items
