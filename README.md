# Martin Monitor

Watches what Martin Lewis and MoneySavingExpert publish, tracks how far it spreads (MSE forum, press, YouTube, Google search), and will tell Compare the Market what it means for them. Built for the CTM pitch. The full plan is in [PLAN.md](PLAN.md).

One Python service does everything: polls each source on a schedule, stores results in SQLite, serves the JSON API and the page, and (from Phase 3) hosts Brian.

## Run it locally

```bash
uv venv --python 3.12 .venv && uv pip install -r requirements.txt --python .venv/bin/python
cp .env.example .env        # then fill in the keys you have; sources with no key are skipped
.venv/bin/python -m app.run mse_news press mse_forum   # run a few sources once
.venv/bin/uvicorn app.main:app --reload --port 8765    # http://localhost:8765
```

`python -m app.run all` runs every enabled source once. With the server running, the scheduler does the same on each source's cadence (set `SCHEDULER=0` to serve without polling).

## Sources

| Key | What | Cadence | Needs |
|---|---|---|---|
| `x` | @MartinSLewis and @MoneySavingExp timelines (own threads kept, replies to others dropped) | 15 min | `BEARER_TOKEN` (paid per tweet) |
| `instagram` | @martinlewismse posts via EnsembleData | 60 min | `ENSEMBLE_TOKEN` |
| `mse_news` | MSE news RSS, each new article fetched for its text | 30 min | none |
| `mse_forum` | Six MSE forum boards via the public Vanilla API | 60 min | none |
| `press` | Google News and Bing News RSS for "Martin Lewis" | 60 min | none |
| `youtube` | Martin's channel uploads and view counts | 12 h | `YOUTUBE_API_KEY` |
| `trends` | Google Trends, worldwide, via Decodo | daily | `DECODO_USERNAME`, `DECODO_PASSWORD` |
| `mse_guides` | Six MSE guide pages, diffed on change | 2 h | none |

Cadences, handles, boards, terms and the topic keyword lists live in `sources.yaml`.

## Layout

```
app/main.py          FastAPI: /health, /api/summary, /api/feed, /api/items/{id}, /api/trends, /api/runs, POST /api/run/{source}
app/scheduler.py     APScheduler in-process; one job per source
app/db.py            SQLite schema and helpers (items, metric_snapshots, trends, insights, runs, state)
app/sources/*.py     one module per source, each exposing fetch(con, cfg) -> list[Item]
app/run.py           run sources from the command line
ui/                  the page: index.html, app.js, styles.css, tokens.css (from the CTM dashboard), fonts, brian.png
sources.yaml         what we watch and how often
fetch_tweets.py      the original standalone tweet downloader; kept for backfills until folded in
```

## Deploy (Railway)

The service runs as one always-on container from the `Dockerfile`. Every push to `main` redeploys.

1. Railway project, New service, GitHub repo `Brainlabs-Digital/Martin-Monitor`, branch `main`.
2. Variables: paste the contents of your `.env`, and set `DATA_DIR=/data`.
3. Volumes: add one, mount path `/data`. The SQLite file lives there and survives deploys.
4. Settings, Networking, Generate Domain. That URL is production.
5. Check `https://<domain>/health`, then open the domain.

Secrets live only in `.env` locally and in Railway's Variables. Nothing is hard-coded, and API keys never appear in error messages (query strings are stripped before logging).

## Why SQLite

One process writes, the same process reads, and the data is a few thousand rows. SQLite in WAL mode handles that with no server to run, back up or pay for. If we ever have several writers or need heavy analytics, the `db.py` layer is the only thing to swap.
