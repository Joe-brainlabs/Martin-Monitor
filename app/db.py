"""SQLite storage: one file in WAL mode, a handful of tables."""

import datetime as dt
import json
import sqlite3

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  kind TEXT NOT NULL,
  external_id TEXT NOT NULL,
  author TEXT,
  title TEXT,
  text TEXT,
  url TEXT,
  published_at TEXT,
  first_seen_at TEXT NOT NULL,
  metrics_json TEXT,
  topics_json TEXT,
  raw_json TEXT,
  brian_json TEXT,
  UNIQUE(source, external_id)
);
CREATE INDEX IF NOT EXISTS items_published ON items(published_at);
CREATE INDEX IF NOT EXISTS items_first_seen ON items(first_seen_at);
CREATE TABLE IF NOT EXISTS metric_snapshots (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES items(id),
  captured_at TEXT NOT NULL,
  metrics_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trends (
  id INTEGER PRIMARY KEY,
  term TEXT NOT NULL,
  geo TEXT NOT NULL,
  resolution TEXT NOT NULL,
  period_start TEXT NOT NULL,
  period_label TEXT NOT NULL,
  value INTEGER,
  captured_at TEXT NOT NULL,
  UNIQUE(term, geo, resolution, period_start)
);
CREATE TABLE IF NOT EXISTS insights (
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL,
  window_start TEXT,
  window_end TEXT,
  headline TEXT,
  body TEXT,
  impact_json TEXT,
  actions_json TEXT,
  confidence TEXT,
  evidence_json TEXT,
  model TEXT
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  ok INTEGER,
  items_new INTEGER,
  error TEXT
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT);
"""


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init() -> None:
    with connect() as con:
        con.executescript(SCHEMA)
        columns = {r["name"] for r in con.execute("PRAGMA table_info(items)")}
        if "brian_json" not in columns:  # databases created before Brian's View existed
            con.execute("ALTER TABLE items ADD COLUMN brian_json TEXT")


def get_state(con: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = con.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    con.commit()


def existing_ids(con: sqlite3.Connection, source: str) -> set[str]:
    return {r["external_id"] for r in con.execute("SELECT external_id FROM items WHERE source = ?", (source,))}


def latest_numeric_id(con: sqlite3.Connection, source: str) -> str | None:
    """Highest external_id for a source whose ids are numeric strings (X tweet ids)."""
    row = con.execute(
        "SELECT MAX(CAST(external_id AS INTEGER)) AS m FROM items WHERE source = ?", (source,)
    ).fetchone()
    return str(row["m"]) if row and row["m"] else None


def upsert_items(con: sqlite3.Connection, items) -> int:
    """Insert new items; for known ones, update metrics and keep a snapshot when they changed."""
    new = 0
    now = utcnow()
    for item in items:
        row = item.to_row(now)
        existing = con.execute(
            "SELECT id, metrics_json, text FROM items WHERE source = ? AND external_id = ?",
            (row["source"], row["external_id"]),
        ).fetchone()
        if existing is not None and row["text"] and (existing["text"] or "").startswith("(article fetch failed") and not row["text"].startswith("(article fetch failed"):
            con.execute("UPDATE items SET text = ?, metrics_json = COALESCE(?, metrics_json) WHERE id = ?", (row["text"], row["metrics_json"], existing["id"]))
        if existing is None:
            con.execute(
                """INSERT INTO items (source, kind, external_id, author, title, text, url, published_at,
                   first_seen_at, metrics_json, topics_json, raw_json)
                   VALUES (:source, :kind, :external_id, :author, :title, :text, :url, :published_at,
                   :first_seen_at, :metrics_json, :topics_json, :raw_json)""",
                row,
            )
            new += 1
        elif row["metrics_json"] and row["metrics_json"] != existing["metrics_json"]:
            con.execute(
                "UPDATE items SET metrics_json = ?, raw_json = ? WHERE id = ?",
                (row["metrics_json"], row["raw_json"], existing["id"]),
            )
            con.execute(
                "INSERT INTO metric_snapshots (item_id, captured_at, metrics_json) VALUES (?, ?, ?)",
                (existing["id"], now, row["metrics_json"]),
            )
    con.commit()
    return new


def upsert_trends(con: sqlite3.Connection, rows: list[dict]) -> int:
    """rows: term, geo, resolution, period_start, period_label, value. Returns how many periods were new."""
    new = 0
    now = utcnow()
    for r in rows:
        known = con.execute(
            "SELECT 1 FROM trends WHERE term = ? AND geo = ? AND resolution = ? AND period_start = ?",
            (r["term"], r["geo"], r["resolution"], r["period_start"]),
        ).fetchone()
        con.execute(
            """INSERT INTO trends (term, geo, resolution, period_start, period_label, value, captured_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(term, geo, resolution, period_start)
               DO UPDATE SET value = excluded.value, period_label = excluded.period_label, captured_at = excluded.captured_at""",
            (r["term"], r["geo"], r["resolution"], r["period_start"], r["period_label"], r["value"], now),
        )
        new += 0 if known else 1
    con.commit()
    return new


def record_run(con: sqlite3.Connection, source: str, started_at: str, ok: bool, items_new: int, error: str | None = None) -> None:
    con.execute(
        "INSERT INTO runs (source, started_at, finished_at, ok, items_new, error) VALUES (?, ?, ?, ?, ?, ?)",
        (source, started_at, utcnow(), int(ok), items_new, error),
    )
    con.commit()


def row_to_item(row: sqlite3.Row) -> dict:
    d = dict(row)
    for key in ("metrics_json", "topics_json", "brian_json"):
        if key in d:
            d[key.removesuffix("_json")] = json.loads(d.pop(key) or "null")
    d.pop("raw_json", None)
    return d
