"""Runs each source on its cadence inside the web process. One process, one scheduler."""

import datetime as dt
import logging
import traceback

from apscheduler.schedulers.background import BackgroundScheduler

from . import db
from .sources import REGISTRY

log = logging.getLogger("martin")


def run_source(name: str) -> dict:
    """Fetch one source once, store what came back, and log the run. Never raises."""
    spec = REGISTRY[name]
    con = db.connect()
    started = db.utcnow()
    try:
        result = spec.fetch(con, spec.cfg)
        new = result if isinstance(result, int) else db.upsert_items(con, result)
        db.record_run(con, name, started, True, new)
        log.info("%s: %d new", name, new)
        return {"source": name, "ok": True, "new": new}
    except Exception as exc:  # a failing source must not take the others down
        message = f"{type(exc).__name__}: {exc}"[:500]
        db.record_run(con, name, started, False, 0, message)
        log.error("%s failed: %s\n%s", name, message, traceback.format_exc(limit=3))
        return {"source": name, "ok": False, "error": message}
    finally:
        con.close()


def build() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    stagger = 5
    for name, spec in REGISTRY.items():
        if not spec.enabled:
            log.warning("%s disabled: %s", name, spec.reason)
            continue
        scheduler.add_job(
            run_source,
            "interval",
            minutes=spec.every_minutes,
            args=[name],
            id=name,
            max_instances=1,
            coalesce=True,
            next_run_time=dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=stagger),
        )
        stagger += 10
    return scheduler
