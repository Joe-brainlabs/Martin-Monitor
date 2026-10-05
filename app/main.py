"""Martin Monitor API and UI. Serves ui/ at /, JSON under /api, and runs the scheduler."""

import datetime as dt
import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import db, relevance
from .config import SOURCES, UI_DIR, env
from .brian import ask as brian_ask
from .brian import client as brian
from .brian import digest as brian_digest
from .brian import views as brian_views
from .queries import ACTIVITY, attach_chains
from .scheduler import build, run_source
from .sources import ITEM_SOURCE_LABELS, REGISTRY, instagram, x

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("martin")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    from .sources.base import retag_all
    con = db.connect()
    try:
        retagged = retag_all(con)
        if retagged:
            log.info("retagged %d items for the CTM sub-brand categories", retagged)
    finally:
        con.close()
    scheduler = build() if os.getenv("SCHEDULER", "1") == "1" else None
    app.state.scheduler = scheduler
    if scheduler:
        scheduler.start()
        log.info("scheduler started with %d jobs", len(scheduler.get_jobs()))
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Martin Monitor", lifespan=lifespan)


@app.middleware("http")
async def no_stale_ui(request: Request, call_next):
    """Make browsers revalidate the page, JS and CSS on every load, so a deploy shows up without a hard refresh."""
    response = await call_next(request)
    if not request.url.path.startswith("/api") and request.url.path.split(".")[-1] in ("", "/", "html", "js", "css") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache"
    return response
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


def labels() -> dict[str, str]:
    return ITEM_SOURCE_LABELS


@app.get("/health")
def health():
    con = db.connect()
    try:
        last = con.execute(
            "SELECT source, MAX(finished_at) AS finished_at FROM runs GROUP BY source"
        ).fetchall()
        # Which keys the running process can see: names and lengths only, never values.
        names = ["BEARER_TOKEN", "ENSEMBLE_TOKEN", "YOUTUBE_API_KEY", "DECODO_USERNAME", "DECODO_PASSWORD", "ANTHROPIC_API_KEY", "ADMIN_TOKEN", "DATA_DIR"]
        keys = {n: (len(env(n)) if env(n) else 0) for n in names}
        near = sorted(k for k in os.environ if "ANTHROPIC" in k.upper() and k != "ANTHROPIC_API_KEY")
        return {
            "ok": True,
            "time": db.utcnow(),
            "commit": (os.getenv("RAILWAY_GIT_COMMIT_SHA") or "local")[:7],
            "keys_set": keys,
            "similar_names": near,
            "last_runs": {r["source"]: r["finished_at"] for r in last},
        }
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
                          SUM(CASE WHEN COALESCE(published_at, first_seen_at) >= ? THEN 1 ELSE 0 END) AS last_24h,
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
        for r in con.execute("SELECT topics_json FROM items WHERE COALESCE(published_at, first_seen_at) >= ? AND topics_json IS NOT NULL", (since,)):
            for t in db.json.loads(r["topics_json"]):
                topics[t] = topics.get(t, 0) + 1
        trend_total = con.execute("SELECT COUNT(*) AS n FROM trends").fetchone()["n"]
        trend_recent = con.execute("SELECT COUNT(*) AS n FROM trends WHERE captured_at >= ?", (since,)).fetchone()["n"]

        def stats(name: str) -> dict:
            if name == "trends":
                return {"total": trend_total, "last_24h": trend_recent, "latest_published": None}
            keys = [k for k in counts if k == name or (name == "x" and k.startswith("x_"))]
            if not keys:
                return {}
            return {
                "total": sum(counts[k]["total"] for k in keys),
                "last_24h": sum(counts[k]["last_24h"] or 0 for k in keys),
                "latest_published": max((counts[k]["latest_published"] or "") for k in keys) or None,
            }

        scheduler = getattr(app.state, "scheduler", None)

        def next_run(name: str) -> str | None:
            job = scheduler.get_job(name) if scheduler else None
            return job.next_run_time.isoformat(timespec="seconds") if job and job.next_run_time else None

        sources = []
        for name, spec in REGISTRY.items():
            sources.append(
                {
                    "source": name,
                    "label": spec.label,
                    "enabled": spec.enabled,
                    "reason": spec.reason,
                    "every_minutes": spec.every_minutes,
                    "next_run": next_run(name),
                    **stats(name),
                    "last_run": {k: v for k, v in runs.get(name, {}).items() if k != "source"} or None,
                }
            )
        usage = db.json.loads(db.get_state(con, "brian_usage", "{}"))
        return {
            "time": db.utcnow(),
            "brian": {
                "enabled": brian.enabled(),
                "model": brian.MODEL,
                "read": db.get_state(con, "brian_read"),
                "read_at": db.get_state(con, "brian_read_at"),
                "usage_today": usage.get(dt.date.today().isoformat(), {}),
            },
            "sources": sources,
            "labels": labels(),
            "by_item_source": {k: {kk: vv for kk, vv in v.items() if kk != "source"} for k, v in counts.items()},
            "topics_24h": topics,
            "topic_names": list(SOURCES["topics"]),
            "topic_defs": SOURCES["topics"],
            "topic_labels": SOURCES.get("topic_labels", {}),
            "trend_terms": [t if isinstance(t, dict) else {"term": t, "topic": None} for t in SOURCES["trends"]["terms"]],
            "martometer": relevance.explain(),
        }
    finally:
        con.close()


@app.get("/api/feed")
def feed(
    limit: int = Query(100, ge=1, le=500),
    source: str | None = None,
    topic: str | None = None,
    since: str | None = None,
    q: str | None = None,
    hide_low: bool = False,
    min_score: float | None = Query(None, ge=0, le=10),
):
    """The feed, newest activity first. Every item carries its Martometer (see app/relevance.py). With hide_low,
    items under the line in sources.yaml are left out and counted in `hidden`; min_score sets your own line."""
    threshold = min_score if min_score is not None else (relevance.HIDE_BELOW if hide_low else None)
    clauses, params = [], []
    if source:
        clauses.append("source = ?"); params.append(source)
    if topic:
        clauses.append("topics_json LIKE ?"); params.append(f'%"{topic}"%')
    if q:
        clauses.append("(title LIKE ? OR text LIKE ? OR author LIKE ?)"); params.extend([f"%{q}%"] * 3)
    if since:
        clauses.append(f"{ACTIVITY} >= ?"); params.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    con = db.connect()
    try:
        rows = con.execute(
            f"""SELECT id, source, kind, external_id, author, title, text, url, published_at, first_seen_at,
                       metrics_json, topics_json, brian_json, {ACTIVITY} AS activity_at
                FROM items {where}
                ORDER BY activity_at DESC LIMIT ?""",
            (*params, 500 if threshold is not None else limit),  # score a wider window, then cut to the limit
        ).fetchall()
        items = [db.row_to_item(r) for r in rows]
        attach_chains(con, items)
        relevance.attach(items)
        hidden = 0
        if threshold is not None:
            kept = [i for i in items if i["martometer"]["score"] >= threshold]
            hidden = len(items) - len(kept)
            items = kept[:limit]
        return {"labels": labels(), "items": items, "hidden": hidden, "hide_below": relevance.HIDE_BELOW}
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
        out["martometer"] = relevance.score(out)
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
        terms = [t if isinstance(t, dict) else {"term": t, "topic": None} for t in SOURCES["trends"]["terms"]]
        return {"geo": SOURCES["trends"]["geo"], "resolution": resolution, "terms": terms, "series": series}
    finally:
        con.close()


@app.get("/api/insights")
def insights(limit: int = Query(20, ge=1, le=100)):
    """Brian's Insights (empty until the Anthropic key is connected and Phase 3 lands)."""
    con = db.connect()
    try:
        rows = con.execute("SELECT * FROM insights ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for key in ("impact_json", "actions_json", "evidence_json"):
                d[key.removesuffix("_json")] = db.json.loads(d.pop(key) or "null")
            out.append(d)
        return {"insights": out, "brian_enabled": brian.enabled(), "read": db.get_state(con, "brian_read"), "read_at": db.get_state(con, "brian_read_at")}
    finally:
        con.close()


@app.get("/api/spread")
def spread():
    """Where a story is spreading: press by publisher, forum boards, Reddit, YouTube. Last 7 days."""
    con = db.connect()
    try:
        now = dt.datetime.now(dt.timezone.utc)
        week = (now - dt.timedelta(days=7)).isoformat(timespec="seconds")
        day = (now - dt.timedelta(hours=24)).isoformat(timespec="seconds")
        press_by_publisher = [
            dict(r) for r in con.execute(
                """SELECT COALESCE(author, 'Unknown') AS publisher, COUNT(*) AS stories FROM items
                   WHERE source = 'press' AND published_at >= ? GROUP BY publisher ORDER BY stories DESC LIMIT 10""", (week,))
        ]
        press_by_day = [
            dict(r) for r in con.execute(
                """SELECT substr(published_at, 1, 10) AS day, COUNT(*) AS stories FROM items
                   WHERE source = 'press' AND published_at >= ? GROUP BY day ORDER BY day""",
                ((now - dt.timedelta(days=14)).isoformat(timespec="seconds"),))
        ]
        boards = []
        for r in con.execute(
            """SELECT json_extract(metrics_json, '$.board') AS board,
                      SUM(CASE WHEN json_extract(metrics_json, '$.last_comment_at') >= ? THEN 1 ELSE 0 END) AS active_24h,
                      SUM(CASE WHEN json_extract(metrics_json, '$.last_comment_at') >= ? THEN 1 ELSE 0 END) AS active_7d,
                      COUNT(*) AS threads
               FROM items WHERE source = 'mse_forum' GROUP BY board ORDER BY active_24h DESC""", (day, week)):
            board = dict(r)
            board["top"] = [
                dict(t) for t in con.execute(
                    """SELECT id, title, url, json_extract(metrics_json, '$.comments') AS comments,
                              json_extract(metrics_json, '$.views') AS views, json_extract(metrics_json, '$.last_comment_at') AS last_comment_at
                       FROM items WHERE source = 'mse_forum' AND json_extract(metrics_json, '$.board') = ?
                         AND json_extract(metrics_json, '$.last_comment_at') >= ?
                       ORDER BY comments DESC LIMIT 3""", (board["board"], week))
            ]
            boards.append(board)
        reddit = {
            "posts_7d": con.execute("SELECT COUNT(*) AS n FROM items WHERE source = 'reddit' AND published_at >= ?", (week,)).fetchone()["n"],
            "mentions_7d": con.execute(
                "SELECT COUNT(*) AS n FROM items WHERE source = 'reddit' AND published_at >= ? AND json_extract(metrics_json, '$.mentions_martin') = 1", (week,)).fetchone()["n"],
            "top": [dict(r) for r in con.execute(
                """SELECT id, title, url, json_extract(metrics_json, '$.subreddit') AS subreddit,
                          json_extract(metrics_json, '$.score') AS score, json_extract(metrics_json, '$.comments') AS comments
                   FROM items WHERE source = 'reddit' AND published_at >= ? ORDER BY score DESC LIMIT 5""", (week,))],
        }
        youtube = [dict(r) for r in con.execute(
            """SELECT id, title, url, published_at, json_extract(metrics_json, '$.views') AS views,
                      json_extract(metrics_json, '$.likes') AS likes, json_extract(metrics_json, '$.comments') AS comments
               FROM items WHERE source = 'youtube' ORDER BY published_at DESC LIMIT 6""")]
        return {"time": db.utcnow(), "press_by_publisher": press_by_publisher, "press_by_day": press_by_day,
                "boards": boards, "reddit": reddit, "youtube": youtube}
    finally:
        con.close()


@app.get("/api/runs")
def runs(limit: int = Query(50, ge=1, le=500)):
    con = db.connect()
    try:
        return [dict(r) for r in con.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))]
    finally:
        con.close()


# "Run now": one background queue, one run at a time. The page's button posts to /api/run/all and follows
# /api/run/status. The sources run in registry order with Brian last, so he reads whatever just arrived.
_RUN: dict = {"running": False, "started_at": None, "finished_at": None, "current": None, "queue": [], "done": []}
_RUN_LOCK = threading.Lock()


def _run_queue() -> None:
    while True:
        with _RUN_LOCK:
            if not _RUN["queue"]:
                _RUN.update(running=False, current=None, finished_at=db.utcnow())
                return
            _RUN["current"] = _RUN["queue"].pop(0)
            name = _RUN["current"]
        result = run_source(name)  # never raises; failures are recorded in the result and the runs table
        with _RUN_LOCK:
            _RUN["done"].append(result)


@app.get("/api/run/status")
def run_status():
    """Progress of the current or last 'run now'. Read-only: source names, counts and error text."""
    with _RUN_LOCK:
        return {**_RUN, "queue": list(_RUN["queue"]), "done": list(_RUN["done"])}


@app.post("/api/run/all", status_code=202)
def run_all(sources: str | None = None, x_admin_token: str | None = Header(default=None)):
    """Run every enabled source now, or the comma-separated `sources`, in the background. Returns at once;
    follow /api/run/status. Admin token required, because X, Decodo, EnsembleData and Brian all cost money."""
    _require_admin(x_admin_token)
    wanted = [n.strip() for n in sources.split(",") if n.strip()] if sources else [n for n, s in REGISTRY.items() if s.enabled]
    unknown = [n for n in wanted if n not in REGISTRY]
    if unknown:
        raise HTTPException(404, f"Unknown source: {', '.join(unknown)}. Known: {', '.join(REGISTRY)}")
    disabled = [n for n in wanted if not REGISTRY[n].enabled]
    if disabled:
        raise HTTPException(400, f"{', '.join(disabled)} is off: {REGISTRY[disabled[0]].reason}")
    names = [n for n in REGISTRY if n in set(wanted)]  # registry order, Brian last
    with _RUN_LOCK:
        if _RUN["running"]:
            raise HTTPException(409, "A run is already in progress")
        _RUN.update(running=True, started_at=db.utcnow(), finished_at=None, current=None, queue=names, done=[])
    threading.Thread(target=_run_queue, name="run-now", daemon=True).start()
    return run_status()


@app.post("/api/run/{name}")
def run_now(name: str, x_admin_token: str | None = Header(default=None)):
    """Trigger one source immediately and wait for it. Server-side token check; disabled unless ADMIN_TOKEN is set.
    Long sources (Trends) can outlast a proxy timeout here; the page uses /api/run/all instead."""
    _require_admin(x_admin_token)
    if name not in REGISTRY:
        raise HTTPException(404, f"Unknown source. Known: {', '.join(REGISTRY)}")
    return run_source(name)


def _require_admin(x_admin_token: str | None) -> None:
    expected = env("ADMIN_TOKEN")
    if not expected:
        raise HTTPException(403, "Admin actions are disabled (ADMIN_TOKEN not set)")
    if x_admin_token != expected:
        raise HTTPException(401, "Bad admin token")


@app.post("/api/backfill/{name}")
def backfill(
    name: str,
    handle: str | None = None,
    max: int = Query(200, ge=1, le=3200),
    replies: str = Query("none", pattern="^(none|own)$"),
    x_admin_token: str | None = Header(default=None),
):
    """Pull history for x (per handle, paid per tweet) or instagram (one Ensemble unit per ten posts)."""
    _require_admin(x_admin_token)
    con = db.connect()
    started = db.utcnow()
    try:
        if name == "x":
            if not handle:
                raise HTTPException(400, "handle is required, e.g. MartinSLewis")
            result = x.backfill(con, REGISTRY["x"].cfg, handle, max, include_replies=(replies == "own"))
        elif name == "instagram":
            result = instagram.backfill(con, REGISTRY["instagram"].cfg, max)
        else:
            raise HTTPException(404, "Backfill supports x and instagram")
        db.record_run(con, f"backfill_{name}", started, True, result.get("stored", 0))
        return result
    except HTTPException:
        raise
    except Exception as exc:
        db.record_run(con, f"backfill_{name}", started, False, 0, str(exc)[:500])
        raise HTTPException(502, str(exc)[:300])
    finally:
        con.close()


def _caller(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return (forwarded.split(",")[0].strip() if forwarded else request.client.host) or "unknown"


class Question(BaseModel):
    question: str


@app.post("/api/brian/ask")
def brian_ask_endpoint(q: Question, request: Request):
    """Live, streamed answer from Brian. Public, so rate-limited per caller and capped in length."""
    if not brian.enabled():
        raise HTTPException(503, "Brian is not connected (ANTHROPIC_API_KEY not set)")
    question = q.question.strip()
    if not question or len(question) > 500:
        raise HTTPException(400, "Ask a question of up to 500 characters")
    caller = _caller(request)
    if not brian_ask.allowed(f"ask:{caller}", brian.CFG.get("ask_per_hour", 20)):
        raise HTTPException(429, "Brian needs a breather: too many questions from here this hour")

    def events():
        con = db.connect()
        try:
            for chunk in brian_ask.stream_answer(con, question, caller):
                yield f"data: {db.json.dumps(chunk)}\n\n"
            yield "event: done\ndata: {}\n\n"
        except Exception as exc:
            log.error("ask failed: %s", exc)
            yield f"data: {db.json.dumps(' (Brian lost the thread: ' + type(exc).__name__ + ')')}\n\n"
        finally:
            con.close()

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/brian/view/{item_id}")
def brian_view_endpoint(item_id: int, request: Request):
    """Write Brian's view for one item on request (items outside the automatic set). Rate-limited per caller."""
    if not brian.enabled():
        raise HTTPException(503, "Brian is not connected (ANTHROPIC_API_KEY not set)")
    if not brian_ask.allowed(f"view:{_caller(request)}", brian.CFG.get("views_per_hour", 30)):
        raise HTTPException(429, "Too many requests this hour")
    con = db.connect()
    try:
        return brian_views.view_item(con, item_id)
    except LookupError:
        raise HTTPException(404, "No such item")
    except Exception as exc:
        log.error("view failed: %s", exc)
        raise HTTPException(502, f"Brian could not read it: {type(exc).__name__}")
    finally:
        con.close()


@app.post("/api/brian/digest")
def brian_digest_endpoint(x_admin_token: str | None = Header(default=None)):
    """Force the digest now (admin)."""
    _require_admin(x_admin_token)
    if not brian.enabled():
        raise HTTPException(503, "Brian is not connected (ANTHROPIC_API_KEY not set)")
    con = db.connect()
    try:
        return {"insights": brian_digest.maybe_run(con, brian.CFG, force=True), "read": db.get_state(con, "brian_read")}
    finally:
        con.close()


@app.post("/api/prune/reddit")
def prune_reddit(x_admin_token: str | None = Header(default=None)):
    """Remove stored Reddit posts that the current keep-rule would not have kept."""
    _require_admin(x_admin_token)
    cfg = REGISTRY["reddit"].cfg
    con = db.connect()
    try:
        ids = [
            r["id"] for r in con.execute(
                """SELECT id FROM items WHERE source = 'reddit'
                   AND COALESCE(json_extract(metrics_json, '$.mentions_martin'), 0) = 0
                   AND COALESCE(json_extract(metrics_json, '$.score'), 0) < ?
                   AND COALESCE(json_extract(metrics_json, '$.comments'), 0) < ?""",
                (cfg.get("min_score", 20), cfg.get("min_comments", 20)),
            )
        ]
        for start in range(0, len(ids), 500):
            batch = ids[start:start + 500]
            marks = ",".join("?" * len(batch))
            con.execute(f"DELETE FROM metric_snapshots WHERE item_id IN ({marks})", batch)
            con.execute(f"DELETE FROM items WHERE id IN ({marks})", batch)
        con.commit()
        return {"removed": len(ids)}
    finally:
        con.close()


def _asset_version() -> str:
    """Short hash of the JS and CSS, so every deploy that changes them gets new asset URLs."""
    import hashlib
    digest = hashlib.sha1()
    for name in ("app.js", "styles.css", "tokens.css"):
        digest.update((UI_DIR / name).read_bytes())
    return digest.hexdigest()[:10]


ASSET_VERSION = _asset_version()


@app.get("/", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
def index():
    """The page, with versioned asset URLs. A CDN in front of us (Cloudflare) caches JS and CSS for hours;
    a new ?v= on each deploy means it can never serve last deploy's script with this deploy's page."""
    html = (UI_DIR / "index.html").read_text()
    for name in ("app.js", "styles.css", "tokens.css"):
        html = html.replace(f'"{name}"', f'"{name}?v={ASSET_VERSION}"')
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


# The UI last, so /api and /health win. StaticFiles handles path containment itself.
app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
