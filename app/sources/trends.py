"""Google Trends via Decodo's Web Scraping API (google_trends_explore). Worldwide by decision:
Decodo rejects the geo parameter on this target, so we do not send one."""

import datetime as dt
import json
import logging
import re
import time

import httpx

from .. import db
from ..config import BROWSER_UA, env

from .base import DECODO_ENDPOINT as ENDPOINT
MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _scrape(body: dict, attempts: int = 3) -> dict:
    """One Decodo scrape. Google Trends refuses scrapers now and then, and Decodo passes that back as a
    2xx with no results, so check the shape and retry before giving up with the real message."""
    last = None
    for attempt in range(attempts):
        response = httpx.post(
            ENDPOINT,
            json=body,
            auth=(env("DECODO_USERNAME"), env("DECODO_PASSWORD")),
            headers={"User-Agent": BROWSER_UA},
            timeout=120,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {"body": response.text[:200]}
        results = payload.get("results") if isinstance(payload, dict) else None
        if response.status_code < 400 and results:
            content = results[0].get("content")
            if isinstance(content, dict) and content.get("interest_over_time"):
                return content
            last = f"HTTP {response.status_code}, no interest_over_time in content: {json.dumps(content)[:160]}"
        else:
            last = f"HTTP {response.status_code}: {json.dumps(payload)[:200]}"
        if response.status_code in (400, 401, 403, 422):
            break  # our fault or auth: retrying will not help
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Decodo trends scrape failed for {body.get('query')!r}: {last}")


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
    new, failures = 0, []
    for entry in cfg["terms"]:
        term = entry["term"] if isinstance(entry, dict) else entry
        try:
            yearly = _scrape({"target": "google_trends_explore", "query": term})
            new += db.upsert_trends(con, _rows(term, geo, "weekly", yearly))
            related = [q.get("query") for q in (yearly.get("related_queries") or [{}])[0].get("items", []) if q.get("query")]
            if related:
                db.set_state(con, f"trends_related:{term}", db.json.dumps(related[:10]))
            recent = _scrape({
                "target": "google_trends_explore", "query": term, "search_type": "web_search",
                "date_start": (today - dt.timedelta(days=cfg.get("recent_days", 30))).isoformat(),
                "date_end": today.isoformat(),
            })
            new += db.upsert_trends(con, _rows(term, geo, "daily", recent))
        except Exception as exc:  # one refused term should not lose the other five
            failures.append(str(exc)[:300])
            log.warning("trends: %s", exc)
    db.set_state(con, "trends_failures", db.json.dumps(failures))
    if failures and len(failures) == len(cfg["terms"]):
        raise RuntimeError("every trends term failed: " + " | ".join(failures)[:800])
    return new
