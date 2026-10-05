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

The `martin-monitor-dev` preview config in `.claude/launch.json` sets `ADMIN_TOKEN=dev` (local only) so the Run now button works on your laptop.

`python -m app.run all` runs every enabled source once. With the server running, the scheduler does the same on each source's cadence (set `SCHEDULER=0` to serve without polling).

## Sources

| Key | What | Cadence | Needs |
|---|---|---|---|
| `x` | @MartinSLewis and @MoneySavingExp timelines (own threads kept, replies to others dropped) | 15 min | `BEARER_TOKEN` (paid per tweet) |
| `instagram` | @martinlewismse posts via EnsembleData | daily for now | `ENSEMBLE_TOKEN` |
| `mse_news` | MSE news RSS, each new article fetched for its text | daily for now | none |
| `mse_forum` | Six MSE forum boards via the public Vanilla API | daily for now | none |
| `press` | Google News and Bing News RSS for "Martin Lewis" | daily for now | none |
| `reddit` | Newest posts in r/UKPersonalFinance and r/AskUK that mention Martin or MSE, plus loud posts (20+ points or comments) on a CTM topic, via EnsembleData | daily for now | `ENSEMBLE_TOKEN` |
| `youtube` | Martin's channel uploads and view counts | daily for now | `YOUTUBE_API_KEY` |
| `trends` | Google Trends, worldwide, via Decodo | daily | `DECODO_USERNAME`, `DECODO_PASSWORD` |
| `mse_guides` | Six MSE guide pages, diffed on change | daily for now | none |

Cadences, handles, boards, terms and the topic keyword lists live in `sources.yaml`. Everything except X runs daily for now; the target cadences are in PLAN.md.

## The page

Four tabs, all on the CTM dashboard's tokens and Figtree:

- **Signals**: the last 24 hours in numbers, search, filters by source and CTM category, and the feed. Every card has a **Martometer** (a speedometer dial in the corner: relevance to CTM out of 10 around the outside, Martin's face in the middle, the needle on the score; see below), a primary "Open on X / Read on MSE" button, an expand button when the text is long, and a **Brian's View** box (a placeholder until the Anthropic key is connected). Items under the Martometer line are hidden until the **Show low relevance** switch is on; a note above the feed says how many. Martin's posts show a "Picked up" chain when MSE or the press ran the same topic within 48 hours. The right-hand panel is Brian's Insights.
- **Demand**: Google Trends for 15 queries, at least one per CTM sub-brand, weekly over 12 months or daily over 30 days, with a dot wherever Martin posted on that topic. Hover for values; a table view sits underneath.
- **Spread**: press pickup by publisher and per day, forum boards with active threads, Reddit and YouTube, last seven days.
- **Sources**: cadence, last run, next run, stored counts, a Run button per source, the category keyword lists, how the Martometer is worked out (with worked examples), and recent runs.

The top bar has a **Run now** button: it asks for the admin token once per tab, runs every enabled source in the background with Brian last, shows progress, and reloads the page when done.

## The Martometer

Every item gets a relevance score out of 10, computed when it is read (never stored), in `app/relevance.py`:

```
Martometer = 10 × Martin × CTM
Martin     = voice × (0.5 + 0.5 × reach)      who is speaking, scaled by how far it travelled
CTM        = Brian's call if he has read it, else the keyword categories
```

Voice: Martin's own channels 1.0, MSE's official output 0.85, a press story about him 0.7, a forum or Reddit thread that names Martin or MSE 0.75, any other forum thread 0.25, any other Reddit post 0.15. Reach is relative to what is normal for the source, on a log scale: a typical post scores 0.5, a big day 1.0, and a post as far below typical as a big day is above it scores 0 (X 50k and 1m impressions, Instagram 200k and 1.5m plays, YouTube 40k and 500k views, forum 5 and 100 comments, Reddit 30 and 1,000 points plus comments). Sources with no engagement data take the midpoint. On the local data that puts a quiet Martin post on a CTM topic at about 3.1 and a loud one at 5.4 before Brian reads it. CTM: Brian's relevance none 0.05, low 0.35, medium 0.7, high 1.0; otherwise no keyword category 0.1, one 0.6, two or more 0.75.

It is a product on purpose: a Martin post about pensions and a forum thread about broadband that never mentions him both score low. On the 1 October database it keeps 4 of 300 forum threads, 22 of 104 press stories and 0 of 5 Reddit posts above the line (3.0), while every one of Martin's posts on a CTM topic stays. All the numbers are in `sources.yaml` under `martometer`, and the Sources tab renders the formula from the same block. `GET /api/feed?hide_low=1` applies the line and returns `hidden`; `min_score=` sets your own.

We store the full text of everything: whole tweets (including X's long posts via `note_tweet`), Instagram captions, MSE articles up to 30k characters, forum and Reddit posts up to 10k, YouTube descriptions. Press items are headline plus link only. Categories are the 14 CTM sub-brands from the CTM dashboard (Car, Home, Pet, Life, Travel, Health, Business, Energy, Broadband, Phones, Credit cards, Current accounts, Mortgages, Loans), matched as whole words with plurals on the keyword lists in `sources.yaml` (shown on the Sources tab). Brian's View gives his own corrected categories. Changing the lists and bumping `TOPICS_VERSION` in `app/sources/base.py` retags everything once at start-up.

Source glyphs are original marks, not the platforms' logos. To use official brand assets, drop them into `ui/` and point the sprite symbols in `index.html` at them.

## Brian

Brian is Claude Opus 5.5 with a persona and a context file (`app/brian/context.md`, a draft of what he knows about Compare the Market: correct it before the pitch). He never runs on page load.

- **Brian's View** is written once per item, by the scheduled `brian` job (hourly, only when there is something new), for Martin's and MSE's own posts, loud forum and Reddit threads and press stories on a CTM topic. Everything else gets an **Ask Brian about this** button that writes the view on request and stores it. Views are structured and the page shows them in two parts: **Impact on CTM** (product line, direction, magnitude, timing: what the signal does to CTM's demand) and **What CTM could do** (up to three actions, each tagged with the lever it pulls: bids, budgets, creative, content, pr or watch). Plus relevance, corrected categories and confidence. A view also re-scores the item's Martometer.
- **Brian's Insights** and the hero's read of the day come from an hourly digest over the last 24 hours, grounded in stored items (each insight carries evidence ids) and the Trends, forum and press numbers.
- **Ask Brian** streams a live answer grounded in the latest read, insights and recent items. Public endpoint, so it is rate-limited per caller (20 an hour) and capped at 500 characters.
- Spend shows on the Sources tab. Six views plus a digest cost about 10 cents in testing; the stable system prompt is cached, so most input tokens are cheap cache reads. Set a monthly limit in the Anthropic console as the backstop.
- Prompt-injection posture: item text sits inside `<item>` tags in the user turn, the persona treats it as data, and Brian has no tools, so the worst case is one stored paragraph that a human reads. Server-side refusal fallbacks are not enabled; refusals are implausible for this material and the extra beta plumbing was not worth it.

Needs `ANTHROPIC_API_KEY` in Railway's Variables. Force a digest with `POST /api/brian/digest` (admin token).

## Admin actions (production)

With `ADMIN_TOKEN` set in Railway's Variables, these endpoints accept `X-Admin-Token` (the page's Run now button uses the first):

```bash
# run every enabled source in the background, Brian last; follow GET /api/run/status (public, read-only)
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" https://<domain>/api/run/all
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" "https://<domain>/api/run/all?sources=press,mse_forum"

# run one source now and wait for it (any key from the Sources table)
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" https://<domain>/api/run/trends

# pull history: X per handle (about $0.005 a tweet fetched), Instagram (one Ensemble unit per ten posts)
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" "https://<domain>/api/backfill/x?handle=MartinSLewis&max=800"
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" "https://<domain>/api/backfill/x?handle=MoneySavingExp&max=200"
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" "https://<domain>/api/backfill/instagram?max=50"

# drop stored Reddit posts the current keep-rule would not keep (after tightening sources.yaml)
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" https://<domain>/api/prune/reddit
```

The X backfill excludes replies by default so every paid tweet is kept; add `&replies=own` to keep his thread continuations (pays for replies to other people too, which are then dropped). Use a long random `ADMIN_TOKEN`: anyone who guesses it can spend X credits.

X engagement is re-read at 1, 6 and 24 hours after each tweet (about 1.5p a tweet) and kept in `metric_snapshots`, which is where velocity comes from.

## Layout

```
app/main.py          FastAPI: /health, /api/summary, /api/feed, /api/items/{id}, /api/trends, /api/runs, POST /api/run/all, /api/run/status
app/relevance.py     the Martometer: relevance to CTM out of 10, from sources.yaml's martometer block
app/scheduler.py     APScheduler in-process; one job per source
app/db.py            SQLite schema and helpers (items, metric_snapshots, trends, insights, runs, state)
app/sources/*.py     one module per source, each exposing fetch(con, cfg) -> list[Item] (x and instagram also expose backfill)
app/run.py           run sources from the command line
ui/                  the page: index.html, app.js, styles.css, tokens.css (from the CTM dashboard), fonts, brian.png
sources.yaml         what we watch and how often
fetch_tweets.py      the original standalone tweet downloader; kept for backfills until folded in
```

## Deploy (Railway)

The service runs as one always-on container from the `Dockerfile`. Every push to `main` redeploys.

1. Railway project, New service, GitHub repo `Joe-brainlabs/Martin-Monitor`, branch `main`.
2. Variables: paste the contents of your `.env`, and add `DATA_DIR=/data` and `PORT=8000` (so the app listens where the domain points).
3. Volume: from the project canvas (not the service settings), right-click the service and choose Attach Volume, or use + Create, Volume. Mount path `/data`. The SQLite file lives there and survives deploys.
4. Service Settings, Deploy: set Healthcheck Path to `/health`. Leave Serverless off (the scheduler needs the process running) and Cron Schedule empty.
5. Service Settings, Networking, Generate Domain. That URL is production.
6. Check `https://<domain>/health`, then open the domain.

Railway's config-as-code (`railway.toml`) is deprecated and new services cannot opt in, so those settings live in the dashboard.

MSE's Cloudflare refuses requests from datacentre IPs such as Railway's (403). The RSS feed and forum API still work; article and guide pages are fetched through Decodo's residential scraping API when the direct request is refused, about ten requests a day.

Secrets live only in `.env` locally and in Railway's Variables. Nothing is hard-coded, and API keys never appear in error messages (query strings are stripped before logging).

## Why SQLite

One process writes, the same process reads, and the data is a few thousand rows. SQLite in WAL mode handles that with no server to run, back up or pay for. If we ever have several writers or need heavy analytics, the `db.py` layer is the only thing to swap.
