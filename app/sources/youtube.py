"""Martin's YouTube channel via the YouTube Data API v3 (free quota; we use a few units a run)."""

from ..config import env
from .base import Item, http_get, to_iso

API = "https://www.googleapis.com/youtube/v3"


def fetch(con, cfg: dict) -> list[Item]:
    key = env("YOUTUBE_API_KEY")
    uploads = "UU" + cfg["channel_id"][2:]  # a channel's uploads playlist shares its id, with a UU prefix
    playlist = http_get(
        f"{API}/playlistItems",
        params={"part": "contentDetails", "playlistId": uploads, "maxResults": 25, "key": key},
    ).json()
    ids = [p["contentDetails"]["videoId"] for p in playlist.get("items", [])]
    if not ids:
        return []
    videos = http_get(
        f"{API}/videos", params={"part": "snippet,statistics", "id": ",".join(ids), "key": key}
    ).json()
    items = []
    for v in videos.get("items", []):
        snippet, stats = v["snippet"], v.get("statistics", {})
        items.append(
            Item(
                source="youtube",
                kind="video",
                external_id=v["id"],
                author=snippet.get("channelTitle"),
                title=snippet.get("title"),
                text=(snippet.get("description") or "")[:5000],
                url=f"https://www.youtube.com/watch?v={v['id']}",
                published_at=to_iso(snippet.get("publishedAt")),
                metrics={
                    "views": int(stats.get("viewCount", 0)),
                    "likes": int(stats.get("likeCount", 0)),
                    "comments": int(stats.get("commentCount", 0)),
                },
                raw={"thumbnail": (snippet.get("thumbnails", {}).get("medium") or {}).get("url")},
            )
        )
    return items
