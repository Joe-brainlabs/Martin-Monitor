"""Brian's hourly digest: a short read of the last 24 hours and one recommendation per channel, grounded in stored items."""

import datetime as dt
import json
from typing import Literal

from pydantic import BaseModel, Field

from .. import db
from . import client as brian
from .views import Action, Impact

# The three channel slots, in the order the page shows them. Anything that fits none of them goes in "other".
CHANNELS = ("search", "programmatic", "seo")


class Insight(BaseModel):
    headline: str = Field(description="A short, specific headline the channel team would act on. Twelve words or fewer.")
    body: str = Field(description="Two or three plain sentences: what happened, what consumers will do, what it means for CTM")
    impact: list[Impact] = Field(description="Which CTM product lines move, which way, how much and when")
    actions: list[Action] = Field(description="Up to three concrete actions for this channel, each tagged with the lever it pulls")
    confidence: Literal["low", "medium", "high"]
    evidence_ids: list[int] = Field(description="Item ids from the context that support this insight")


class Digest(BaseModel):
    daily_read: str = Field(
        description="At most 45 words, one or two plain sentences: what the last 24 hours mean for Compare the Market. "
        "Lead with the one thing that matters. If nothing happened, say so in one sentence."
    )
    search: Insight | None = Field(
        description="Paid search. The one recommendation for CTM's search team this week: bids, budgets, query coverage, "
        "ad copy that echoes his phrasing. Null only when nothing in the window is relevant to CTM for this channel."
    )
    programmatic: Insight | None = Field(
        description="Programmatic: display, online video including YouTube, connected TV and audio. The one recommendation "
        "for the programmatic team: audiences, contextual placements, video or display creative, pacing, flighting around "
        "the Money Show. Null only when nothing in the window is relevant to CTM for this channel."
    )
    seo: Insight | None = Field(
        description="SEO and content. The one recommendation for the organic team: which guide or page to publish or refresh, "
        "which query to target, how to word the title, timing. Null only when nothing in the window is relevant to CTM for this channel."
    )
    other: list[Insight] = Field(
        description="At most two further insights that fit none of the three channels: PR, a brand risk, something to watch. Usually empty."
    )

    def channelled(self) -> list[tuple[str, Insight]]:
        """(channel, insight) pairs in display order: the three channel slots that were filled, then the rest."""
        slots = [(c, getattr(self, c)) for c in CHANNELS]
        return [(c, i) for c, i in slots if i is not None] + [("other", i) for i in self.other[:2]]


def context_pack(con, hours: int = 24) -> str:
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).isoformat(timespec="seconds")
    rows = con.execute(
        """SELECT id, source, author, title, text, published_at, metrics_json, topics_json, brian_json FROM items
           WHERE COALESCE(published_at, first_seen_at) >= ? AND (brian_json IS NOT NULL OR source IN ('x_martinslewis', 'instagram', 'mse_news'))
           ORDER BY COALESCE(published_at, first_seen_at) DESC LIMIT 60""",
        (since,),
    ).fetchall()
    lines = []
    for r in rows:
        item = db.row_to_item(r)
        view = item.get("brian") or {}
        if view.get("relevance") == "none":
            continue
        m = item.get("metrics") or {}
        eng = ", ".join(f"{k} {v}" for k, v in m.items() if k in ("like_count", "retweet_count", "impression_count", "likes", "comments", "views", "score"))
        text = (item.get("title") or "") + " " + (item.get("text") or "")
        lines.append(
            f"[id {item['id']}] {item['source']} {item.get('author') or ''} {item.get('published_at') or ''} | {eng or 'no engagement data'}\n"
            f"  {text.strip()[:400]}\n  brian: {view.get('summary', 'not read')} (relevance {view.get('relevance', '?')})"
        )
    trends = con.execute(
        """SELECT term, period_label, value FROM trends WHERE resolution = 'daily'
           AND period_start >= date('now', '-7 day') ORDER BY term, period_start"""
    ).fetchall()
    by_term: dict[str, list] = {}
    for t in trends:
        by_term.setdefault(t["term"], []).append(t["value"])
    trend_lines = [f"  {term}: {' '.join(str(v) for v in vals)}" for term, vals in by_term.items()]
    boards = con.execute(
        """SELECT json_extract(metrics_json, '$.board') AS board, COUNT(*) AS n FROM items
           WHERE source = 'mse_forum' AND json_extract(metrics_json, '$.last_comment_at') >= ? GROUP BY board ORDER BY n DESC""",
        (since,),
    ).fetchall()
    press = con.execute("SELECT COUNT(*) AS n FROM items WHERE source = 'press' AND published_at >= ?", (since,)).fetchone()["n"]
    return (
        f"<context>\nnow: {db.utcnow()}\n\nITEMS (last {hours} hours, newest first):\n" + "\n".join(lines) +
        f"\n\nGOOGLE TRENDS (worldwide, daily index, last 7 days):\n" + "\n".join(trend_lines) +
        f"\n\nMSE FORUM threads with new comments in the window:\n" + "\n".join(f"  {b['board']}: {b['n']}" for b in boards) +
        f"\n\nPRESS stories mentioning Martin Lewis in the window: {press}\n</context>"
    )


INSTRUCTION = (
    "Write Brian's read of the window, then one recommendation each for paid search, programmatic (display and video) and SEO, "
    "each with the actions that channel's team could take this week. Leave a channel null only when nothing in the window is "
    "relevant to Compare the Market for it: an empty slot beats a padded one. Anything else that matters goes in other."
)


def maybe_run(con, cfg: dict, new_views: int = 0, force: bool = False) -> int:
    """Write a digest when there is something new, or when the last read is older than six hours."""
    last = db.get_state(con, "brian_read_at")
    stale = not last or (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(last)) > dt.timedelta(hours=6)
    if not force and not new_views and not stale:
        return 0
    response = brian.client().messages.parse(
        model=brian.MODEL,
        max_tokens=6000,
        system=brian.system_blocks(),
        messages=[{"role": "user", "content": context_pack(con, cfg.get("digest_hours", 24)) + "\n\n" + INSTRUCTION}],
        output_format=Digest,
    )
    digest = response.parsed_output
    now = db.utcnow()
    window_start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=cfg.get("digest_hours", 24))).isoformat(timespec="seconds")
    written = digest.channelled()
    for channel, ins in written:
        con.execute(
            """INSERT INTO insights (created_at, window_start, window_end, channel, headline, body, impact_json, actions_json, confidence, evidence_json, model)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, window_start, now, channel, ins.headline, ins.body, json.dumps([i.model_dump() for i in ins.impact]),
             json.dumps([a.model_dump() for a in ins.actions]), ins.confidence, json.dumps(ins.evidence_ids), brian.MODEL),
        )
    con.commit()
    db.set_state(con, "brian_read", digest.daily_read)
    db.set_state(con, "brian_read_at", now)
    brian.record_usage(con, response.usage, "digest")
    return len(written)
