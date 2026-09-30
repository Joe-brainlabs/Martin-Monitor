"""MSE forum: Vanilla Forums' public JSON API, one call per board, newest activity first."""

from .base import Item, http_get, strip_html, to_iso

API = "https://forums.moneysavingexpert.com/api/v2/discussions"


def fetch(con, cfg: dict) -> list[Item]:
    items = []
    for board_id, board in cfg["boards"].items():
        discussions = http_get(
            API, params={"categoryID": board_id, "sort": "-dateLastComment", "limit": cfg.get("per_board", 50)}
        ).json()
        for d in discussions:
            items.append(
                Item(
                    source="mse_forum",
                    kind="thread",
                    external_id=str(d["discussionID"]),
                    author=(d.get("insertUser") or {}).get("name"),
                    title=d.get("name"),
                    text=strip_html(d.get("body"), limit=10000),
                    url=d.get("url"),
                    published_at=to_iso(d.get("dateInserted")),
                    metrics={
                        "board": board,
                        "comments": d.get("countComments", 0),
                        "views": d.get("countViews", 0),
                        "last_comment_at": d.get("dateLastComment"),
                    },
                    raw={k: d.get(k) for k in ("discussionID", "categoryID", "dateLastComment", "countComments", "countViews")},
                )
            )
    return items
