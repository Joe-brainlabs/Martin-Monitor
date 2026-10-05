"""The Martometer: how relevant an item is to Compare the Market's business, 0 to 10.

    Martometer = 10 x Martin x CTM
    Martin (0 to 1) = voice x (floor + (1 - floor) x reach)   who is speaking, nudged by how far it travelled
    CTM    (0 to 1) = Brian's relevance call when he has read the item, otherwise the keyword categories

It is a multiple on purpose: a Martin post about pensions and a forum thread about broadband that never
mentions him both score low, because each is missing one half. The numbers live in sources.yaml under
`martometer`, and the Sources tab renders the formula from the same block, so the page always explains
what the code really does. Scores are computed when items are read, never stored, so a change to the
numbers or a new Brian's View shows at once.
"""

import math
import re

from .config import SOURCES

CFG: dict = SOURCES.get("martometer", {})
VOICE: dict = CFG.get("voice", {})
REACH_REFS: dict = CFG.get("reach_refs", {})
FLOOR = float(CFG.get("reach_floor", 0.7))
CTM_BRIAN: dict = CFG.get("ctm_brian", {"none": 0.05, "low": 0.35, "medium": 0.7, "high": 1.0})
CTM_KEYWORDS: dict[int, float] = {int(k): float(v) for k, v in CFG.get("ctm_keywords", {0: 0.1, 1: 0.6, 2: 0.75}).items()}
HIDE_BELOW = float(CFG.get("hide_below", 3.0))
_MENTION = re.compile(r"\b(?:" + "|".join(re.escape(t.lower()) for t in CFG.get("mention_terms", ["martin lewis"])) + r")\b")

MARTIN_SOURCES = ("x_martinslewis", "instagram", "youtube")
MSE_SOURCES = ("x_moneysavingexp", "mse_news", "mse_guides")


def _voice(item: dict) -> tuple[float, str]:
    source = item["source"]
    if source in MARTIN_SOURCES:
        return float(VOICE.get("martin", 1.0)), "Martin's own post"
    if source in MSE_SOURCES:
        return float(VOICE.get("mse", 0.85)), "MSE's official output"
    if source == "press":
        return float(VOICE.get("press", 0.7)), "press story about Martin"
    text = f"{item.get('title') or ''} {item.get('text') or ''}".lower()
    if (item.get("metrics") or {}).get("mentions_martin") or _MENTION.search(text):
        return float(VOICE.get("names_martin", 0.75)), "thread that names Martin or MSE"
    if source == "mse_forum":
        return float(VOICE.get("forum", 0.25)), "forum thread, Martin not named"
    return float(VOICE.get("reddit", 0.15)), "Reddit post, Martin not named"


def _reach(item: dict) -> tuple[float | None, str]:
    """0 to 1 on a log scale against the source's full-reach reference; None when the source has no engagement data."""
    m = item.get("metrics") or {}
    source = item["source"]
    if source.startswith("x_"):
        n, ref, what = m.get("impression_count") or (m.get("like_count") or 0) * 100, REACH_REFS.get("x"), "impressions"
    elif source == "instagram":
        n, ref, what = m.get("views") or (m.get("likes") or 0) * 15, REACH_REFS.get("instagram"), "plays"
    elif source == "youtube":
        n, ref, what = m.get("views") or 0, REACH_REFS.get("youtube"), "views"
    elif source == "mse_forum":
        n, ref, what = m.get("comments") or 0, REACH_REFS.get("mse_forum"), "comments"
    elif source == "reddit":
        n, ref, what = (m.get("score") or 0) + (m.get("comments") or 0), REACH_REFS.get("reddit"), "points and comments"
    else:
        return None, "no engagement data"
    if not ref:
        return None, "no engagement data"
    n = max(0, int(n or 0))
    return min(1.0, math.log10(1 + n) / math.log10(1 + ref)), f"{n:,} {what}"


def _ctm(item: dict) -> tuple[float, str]:
    relevance = (item.get("brian") or {}).get("relevance")
    if relevance in CTM_BRIAN:
        return float(CTM_BRIAN[relevance]), f"Brian: relevance {relevance}"
    topics = item.get("topics") or []
    labels = SOURCES.get("topic_labels", {})
    names = ", ".join(labels.get(t, t) for t in topics) or "none"
    return CTM_KEYWORDS.get(min(len(topics), max(CTM_KEYWORDS)), 0.1), f"keyword categories: {names}"


def score(item: dict) -> dict:
    voice, who = _voice(item)
    reach, seen = _reach(item)
    martin = voice * (FLOOR + (1 - FLOOR) * (0.5 if reach is None else reach))
    ctm, why = _ctm(item)
    value = round(10 * martin * ctm, 1)
    return {
        "score": value, "martin": round(martin, 2), "ctm": round(ctm, 2),
        "voice": voice, "reach": None if reach is None else round(reach, 2),
        "who": who, "seen": seen, "why": why, "low": value < HIDE_BELOW,
    }


def attach(items: list[dict]) -> None:
    for item in items:
        item["martometer"] = score(item)


def explain() -> dict:
    """The constants, for the Sources tab to render the formula as it really runs."""
    return {
        "hide_below": HIDE_BELOW, "voice": VOICE, "reach_floor": FLOOR, "reach_refs": REACH_REFS,
        "ctm_brian": CTM_BRIAN, "ctm_keywords": {str(k): v for k, v in CTM_KEYWORDS.items()},
        "mention_terms": CFG.get("mention_terms", []),
    }
