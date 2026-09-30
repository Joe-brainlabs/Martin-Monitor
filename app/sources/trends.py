"""Google Trends via Decodo's Web Scraping API (google_trends_explore). Worldwide by decision:
Decodo rejects the geo parameter on this target, so we do not send one."""

import datetime as dt
import re

import httpx

from .. import db
from ..config import BROWSER_UA, env

from .base import DECODO_ENDPOINT as ENDPOINT
MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _scrape(body: dict) -> dict:
    response = httpx.post(
        ENDPOINT,
        json=body,
        auth=(env("DECODO_USERNAME"), env("DECODO_PASSWORD")),
        headers={"User-Agent": BROWSER_UA},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["results"][0]["content"]


def period_start(label: str) -> str | None:
    """'Sep 28 – Oct 4, 2025' -> 2025-09-28; 'Dec 28 – Jan 3, 2026' -> 2025-12-28; 'Sep 23, 2026' -> 2026-09-23."""
    clean = label.replace(" ", " ").replace("–", "-")
    dates = re.findall(r"([A-Z][a-z]{2}) (\d{1,2})(?:, (\d{4}))?", clean)
    years = re.findall(r"\b(20\d{2})\b", clean)
    if not dates or not years:
        return None
    month, day, year = dates[0]
    year = int(year or years[-1])
    if not dates[0][2] and len(dates) > 1 and MONTHS[month] > MONTHS[dates[-1][0]]:
        year -= 1  # a range that crosses New Year carries only the end year
    return dt.date(year, MONTHS[month], int(day)).isoformat()


def _rows(term: str, geo: str, resolution: str, content: dict) -> list[dict]:
    rows = []
    for series in content.get("interest_over_time", []):
        for point in series.get("items", []):
            start = period_start(point.get("time", ""))
            if start:
                rows.append({"term": term, "geo": geo, "resolution": resolution, "period_start": start,
                             "period_label": point["time"], "value": point.get("value")})
    return rows


def fetch(con, cfg: dict) -> int:
    geo = cfg.get("geo", "WORLD")
    today = dt.date.today()
    new = 0
    for term in cfg["terms"]:
        yearly = _scrape({"target": "google_trends_explore", "query": term})
        new += db.upsert_trends(con, _rows(term, geo, "weekly", yearly))
        recent = _scrape({
            "target": "google_trends_explore", "query": term, "search_type": "web_search",
            "date_start": (today - dt.timedelta(days=cfg.get("recent_days", 30))).isoformat(),
            "date_end": today.isoformat(),
        })
        new += db.upsert_trends(con, _rows(term, geo, "daily", recent))
        related = [q.get("query") for q in (yearly.get("related_queries") or [{}])[0].get("items", []) if q.get("query")]
        if related:
            db.set_state(con, f"trends_related:{term}", db.json.dumps(related[:10]))
    return new
