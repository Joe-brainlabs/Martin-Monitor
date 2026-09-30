"""Martin Monitor API and UI. Serves ui/ at /, JSON under /api, and runs the scheduler."""

import datetime as dt
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import db
from .config import SOURCES, UI_DIR, env
from .scheduler import build, run_source
from .sources import ITEM_SOURCE_LABELS, REGISTRY

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("martin")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    scheduler = build() if os.getenv("SCHEDULER", "1") == "1" else None
    if scheduler:
        scheduler.start()
        log.info("scheduler started with %d jobs", len(scheduler.get_jobs()))
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Martin Monitor", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


# When an item was last active: a forum thread's latest comment, otherwise when it was published.
ACTIVITY = "COALESCE(json_extract(metrics_json, '$.last_comment_at'), published_at, first_seen_at)"


def labels() -> dict[str, str]:
    return ITEM_SOURCE_LABELS


@app.get("/health")
def health():
    con = db.connect()
    try:
        last = con.execute(
            "SELECT source, MAX(finished_at) AS finished_at FROM runs GROUP BY source"
        ).fetchall()
        return {"ok": True, "time": db.utcnow(), "last_runs": {r["source"]: r["finished_at"] for r in last}}
    finally:
        con.close()


@app.get("/api/summary")
def summary():
    con = db.connect()
    try:
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)).isoformat(timespec="seconds")
        counts = {
            r["source"]: dict(r)
            for r in con.execute(
                """SELECT source, COUNT(*) AS total,
                          SUM(CASE WHEN first_seen_at >= ? THEN 1 ELSE 0 END) AS last_24h,
                          MAX(published_at) AS latest_published
                   FROM items GROUP BY source""",
                (since,),
            )
        }
        runs = {
            r["source"]: dict(r)
            for r in con.execute(
                """SELECT source, started_at, finished_at, ok, items_new, error FROM runs
                   WHERE id IN (SELECT MAX(id) FROM runs GROUP BY source)"""
            )
        }
        topics: dict[str, int] = {}
        for r in con.execute("SELECT topics_json FROM items WHERE first_seen_at >= ? AND topics_json IS NOT NULL", (since,)):
            for t in db.json.loads(r["topics_json"]):
                topics[t] = topics.get(t, 0) + 1
        def stats(name: str) -> dict:
            keys = [k for k in counts if k == name or (name == "x" and k.startswith("x_"))]
            if not keys:
                return {}
            return {
                "total": sum(counts[k]["total"] for k in keys),
                "last_24h": sum(counts[k]["last_24h"] or 0 for k in keys),
                "latest_published": max((counts[k]["latest_published"] or "") for k in keys) or None,
            }

        sources = []
        for name, spec in REGISTRY.items():
            sources.append(
                {
                    "source": name,
                    "label": spec.label,
                    "enabled": spec.enabled,
                    "every_minutes": spec.every_minutes,
                    **stats(name),
                    "last_run": {k: v for k, v in runs.get(name, {}).items() if k != "source"} or None,
                }
            )
        return {"time": db.utcnow(), "sources": sources, "topics_24h": topics, "topic_names": list(SOURCES["topics"])}
    finally:
        con.close()


@app.get("/api/feed")
def feed(
    limit: int = Query(100, ge=1, le=500),
    source: str | None = None,
    topic: str | None = None,
    since: str | None = None,
):
    clauses, params = [], []
    if source:
        clauses.append("source = ?"); params.append(source)
    if topic:
        clauses.append("topics_json LIKE ?"); params.append(f'%"{topic}"%')
    if since:
        clauses.append(f"{ACTIVITY} >= ?"); params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    con = db.connect()
    try:
        rows = con.execute(
            f"""SELECT id, source, kind, external_id, author, title, text, url, published_at, first_seen_at,
                       metrics_json, topics_json, {ACTIVITY} AS activity_at
                FROM items {where}
                ORDER BY activity_at DESC LIMIT ?""",
            (*params, limit),
        ).fetchall()
        return {"labels": labels(), "items": [db.row_to_item(r) for r in rows]}
    finally:
        con.close()


@app.get("/api/items/{item_id}")
def item(item_id: int):
    con = db.connect()
    try:
        row = con.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(404, "No such item")
        snapshots = con.execute(
            "SELECT captured_at, metrics_json FROM metric_snapshots WHERE item_id = ? ORDER BY captured_at", (item_id,)
        ).fetchall()
        out = db.row_to_item(row)
        out["snapshots"] = [{"captured_at": s["captured_at"], "metrics": db.json.loads(s["metrics_json"])} for s in snapshots]
        return out
    finally:
        con.close()


@app.get("/api/trends")
def trends(term: str | None = None, resolution: str = "weekly"):
    con = db.connect()
    try:
        clauses, params = ["resolution = ?"], [resolution]
        if term:
            clauses.append("term = ?"); params.append(term)
        rows = con.execute(
            f"SELECT term, geo, resolution, period_start, period_label, value FROM trends WHERE {' AND '.join(clauses)} ORDER BY term, period_start",
            params,
        ).fetchall()
        series: dict[str, list] = {}
        for r in rows:
            series.setdefault(r["term"], []).append({"period_start": r["period_start"], "label": r["period_label"], "value": r["value"]})
        return {"geo": SOURCES["trends"]["geo"], "resolution": resolution, "series": series}
    finally:
        con.close()


@app.get("/api/runs")
def runs(limit: int = Query(50, ge=1, le=500)):
    con = db.connect()
    try:
        return [dict(r) for r in con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))]
    finally:
        con.close()


@app.post("/api/run/{name}")
def run_now(name: str, x_admin_token: str | None = Header(default=None)):
    """Trigger one source immediately. Server-side token check; disabled unless ADMIN_TOKEN is set."""
    expected = env("ADMIN_TOKEN")
    if not expected:
        raise HTTPException(403, "Manual runs are disabled (ADMIN_TOKEN not set)")
    if x_admin_token != expected:
        raise HTTPException(401, "Bad admin token")
    if name not in REGISTRY:
        raise HTTPException(404, f"Unknown source. Known: {', '.join(REGISTRY)}")
    return run_source(name)


# The UI last, so /api and /health win. StaticFiles handles path containment itself.
app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
