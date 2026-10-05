"""Ask Brian: a live, streamed answer grounded in the latest read, insights and recent items."""

import collections
import datetime as dt
import json
import time

from .. import db
from . import client as brian
from .digest import context_pack

_hits: dict[str, collections.deque] = collections.defaultdict(collections.deque)


def allowed(key: str, per_hour: int) -> bool:
    """Sliding-window rate limit per caller, in memory (one process, so this is enough)."""
    now = time.time()
    q = _hits[key]
    while q and q[0] < now - 3600:
        q.popleft()
    if len(q) >= per_hour:
        return False
    q.append(now)
    return True


def _grounding(con) -> str:
    read = db.get_state(con, "brian_read") or "No read written yet."
    rows = con.execute("SELECT channel, headline, body, confidence FROM insights ORDER BY id DESC LIMIT 6").fetchall()
    insights = "\n".join(f"- [{r['channel'] or 'general'}] {r['headline']} ({r['confidence']}): {r['body']}" for r in rows) or "- none yet"
    return f"Brian's latest read: {read}\n\nLatest insights:\n{insights}\n\n{context_pack(con, 48)}"


def stream_answer(con, question: str, caller: str):
    """Yield text chunks. The question is the user's own words; it goes in the user turn as a question."""
    prompt = (
        f"{_grounding(con)}\n\nA Compare the Market stakeholder asks: {question.strip()[:500]}\n\n"
        "Answer in under 200 words, in plain British English, grounded in the context above. "
        "If the context does not cover it, say so rather than guessing."
    )
    answer = []
    with brian.client().messages.stream(
        model=brian.MODEL, max_tokens=1200, system=brian.system_blocks(),
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for text in stream.text_stream:
            answer.append(text)
            yield text
        final = stream.get_final_message()
    con.execute(
        "INSERT INTO asks (created_at, question, answer, caller, input_tokens, output_tokens) VALUES (?, ?, ?, ?, ?, ?)",
        (db.utcnow(), question[:500], "".join(answer), caller, final.usage.input_tokens, final.usage.output_tokens),
    )
    con.commit()
    brian.record_usage(con, final.usage, "ask")
