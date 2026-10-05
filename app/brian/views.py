"""Brian's View: one structured judgement per item, written once and stored on the item."""

import datetime as dt
import json
from typing import Literal

from pydantic import BaseModel, Field

from .. import db
from ..config import SOURCES
from ..queries import attach_chains
from . import client as brian

TOPICS = tuple(SOURCES["topics"].keys())
Topic = Literal[TOPICS]  # type: ignore[valid-type]
Product = Literal[TOPICS + ("other",)]  # type: ignore[valid-type]


class Impact(BaseModel):
    product: Product
    direction: Literal["up", "down", "mixed", "none"] = Field(description="Which way comparison demand for CTM moves")
    magnitude: Literal["small", "medium", "large"]
    timing: str = Field(description="When it bites, in words, e.g. 'next 24 to 72 hours'")


class Action(BaseModel):
    lever: Literal["bids", "budgets", "targeting", "creative", "content", "pr", "watch"] = Field(
        description="The lever CTM pulls: bids (paid search bids or query coverage), budgets (move spend between product lines "
        "or channels, lift or cut pacing), targeting (programmatic audiences, contextual placements, YouTube or connected TV targeting), "
        "creative (ad copy, display, video or social creative that echoes the advice), content (landing pages, guides, SEO), "
        "pr (get named, respond, partner), watch (monitor, no spend yet)"
    )
    text: str = Field(description="The action in one plain sentence")


class View(BaseModel):
    relevance: Literal["none", "low", "medium", "high"] = Field(description="How much this matters to Compare the Market")
    summary: str = Field(description="One or two plain sentences: what this means for CTM. If relevance is none, say why in one sentence.")
    impact: list[Impact] = Field(description="Which CTM product lines move, which way, how much and when. Empty when relevance is none")
    search: list[Action] = Field(
        description="Paid search: up to two actions for CTM's search team (bids, budgets, query coverage, ad copy that echoes his phrasing). "
        "Empty when this item gives paid search nothing to do."
    )
    programmatic: list[Action] = Field(
        description="Programmatic: display, online video including YouTube, connected TV and audio. Up to two actions (targeting, creative, "
        "budgets or pacing). Empty when this item gives programmatic nothing to do."
    )
    seo: list[Action] = Field(
        description="SEO and content: up to two actions (which guide or page to publish or refresh, which query, how to word the title, timing). "
        "Empty when this item gives organic nothing to do."
    )
    other: list[Action] = Field(description="Anything that fits none of the three channels: pr or watch. Usually empty.")
    topics: list[Topic] = Field(description="The CTM categories this item is really about (corrects the keyword tags)")
    confidence: Literal["low", "medium", "high"]


def eligible(con, cfg: dict, limit: int) -> list[dict]:
    """Items without a view that Brian reads automatically: Martin and MSE's own output, loud threads, press on a CTM topic."""
    auto = cfg.get("auto_sources", [])
    loud = cfg.get("loud_sources", {})
    clauses = [f"source IN ({','.join('?' * len(auto))})"] if auto else []
    params: list = list(auto)
    for source, threshold in loud.items():
        clauses.append("(source = ? AND COALESCE(json_extract(metrics_json, '$.comments'), 0) >= ?)")
        params.extend([source, threshold])
    if cfg.get("press_with_topic", True):
        clauses.append("(source = 'press' AND topics_json != '[]')")
    rows = con.execute(
        f"""SELECT id, source, kind, author, title, text, url, published_at, metrics_json, topics_json, brian_json
            FROM items WHERE brian_json IS NULL AND ({' OR '.join(clauses)})
            ORDER BY COALESCE(published_at, first_seen_at) DESC LIMIT ?""",
        (*params, limit),
    ).fetchall()
    items = [db.row_to_item(r) for r in rows]
    attach_chains(con, items)
    return items


def parent_text(con, item: dict) -> str | None:
    """For a tweet in one of Martin's own threads, the tweet it replies to, if we have it."""
    if not item["source"].startswith("x_"):
        return None
    row = con.execute("SELECT raw_json FROM items WHERE id = ?", (item["id"],)).fetchone()
    raw = db.json.loads(row["raw_json"] or "{}") if row else {}
    parent_id = next((r.get("id") for r in raw.get("referenced_tweets") or [] if r.get("type") == "replied_to"), None)
    if not parent_id:
        return None
    parent = con.execute("SELECT text FROM items WHERE source = ? AND external_id = ?", (item["source"], parent_id)).fetchone()
    return parent["text"] if parent else None


def item_prompt(item: dict, parent: str | None = None) -> str:
    m = item.get("metrics") or {}
    metrics = ", ".join(f"{k} {v}" for k, v in m.items() if k not in ("description", "via", "query") and v not in (None, "", False))
    chain = item.get("chain") or {}
    pickup = []
    if chain.get("mse"):
        pickup.append(f"MSE ran it ({len(chain['mse'])})")
    if chain.get("press"):
        pickup.append("press pickup: " + ", ".join(p.get("publisher") or "unknown" for p in chain["press"]))
    label = SOURCES["topics"] and (item.get("topics") or [])
    # Prompt injection surface: the item text is other people's writing. It sits inside <item> tags in the
    # user turn, the persona says to treat it as data, and Brian has no tools, so the blast radius is one
    # stored paragraph that a human reads.
    return (
        f"<item>\nsource: {item['source']}\nkind: {item['kind']}\nauthor: {item.get('author') or 'unknown'}\n"
        f"published: {item.get('published_at') or 'unknown'}\nkeyword tags: {', '.join(label) or 'none'}\n"
        f"engagement: {metrics or 'none recorded'}\npickup so far: {'; '.join(pickup) or 'none seen'}\n"
        f"title: {item.get('title') or ''}\n"
        + (f"in reply to (earlier post in the same thread): {parent[:1500]}\n" if parent else "")
        + f"\n{(item.get('text') or '')[:6000]}\n</item>\n\n"
        "Assess this item for Compare the Market: the impact, then what each channel team should do about it (paid search, "
        "programmatic, SEO). Leave a channel empty when the item gives it nothing: an empty section beats a padded one."
    )


def write_view(con, item: dict) -> dict:
    response = brian.client().messages.parse(
        model=brian.MODEL,
        max_tokens=1500,
        system=brian.system_blocks(),
        messages=[{"role": "user", "content": item_prompt(item, parent_text(con, item))}],
        output_format=View,
    )
    view = response.parsed_output.model_dump()
    view["model"] = brian.MODEL
    view["created_at"] = db.utcnow()
    con.execute("UPDATE items SET brian_json = ? WHERE id = ?", (json.dumps(view), item["id"]))
    con.commit()
    brian.record_usage(con, response.usage, "view")
    return view


def view_item(con, item_id: int) -> dict:
    row = con.execute(
        "SELECT id, source, kind, author, title, text, url, published_at, metrics_json, topics_json, brian_json FROM items WHERE id = ?",
        (item_id,),
    ).fetchone()
    if not row:
        raise LookupError("no such item")
    item = db.row_to_item(row)
    if item.get("brian"):
        return item["brian"]
    attach_chains(con, [item])
    return write_view(con, item)


def fetch(con, cfg: dict) -> int:
    """The scheduled Brian pass: views for new eligible items, then the digest if there is anything new."""
    from . import digest

    written = 0
    for item in eligible(con, cfg, cfg.get("per_run_cap", 25)):
        write_view(con, item)
        written += 1
    digest.maybe_run(con, cfg, new_views=written)
    return written
