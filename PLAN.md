# Martin Monitor: build plan

Draft 1, 30 September 2026. For the Compare the Market (CTM) pitch. Written to be built fast on Joe's own accounts, with no Cortex approvals in the path.

## What we are building

Martin Monitor watches what Martin Lewis and MoneySavingExpert (MSE) publish, tracks how far each story spreads (MSE forum, Reddit, national press, Google search), and tells CTM what it means for them within the hour. One live web page, refreshed automatically, with a panel where Brian (the beaver from the CTM dashboard) reads the signals and suggests what CTM should do about bids, budgets and content.

The pitch version has to work end to end and look good on a big screen. It does not need to scale, and it does not need a login, because everything it shows is already public.

## Decisions at a glance

| Decision | Choice | Why |
|---|---|---|
| Language | Python 3.12 (FastAPI, APScheduler, httpx, SQLite) | One language for the pollers, the API and Brian. Reuses `fetch_tweets.py`. |
| Hosting | Railway: one always-on service with a small persistent volume | One repo, one deploy, one URL, one process. Joe's account, no approvals, about $5 to $10 a month. |
| Storage | SQLite on the volume, nightly JSON export as a backup | A few thousand rows. A database server would be admin for nothing. |
| Scheduling | APScheduler running inside the service | Cadences live in one config file. No cron infrastructure. |
| UI | Static single page served by the same service, using the CTM dashboard's tokens, fonts and Brian assets | Looks like part of the pitch dashboard. No build step. |
| Brian | Claude Opus 5.5 through the Anthropic Python SDK, server-side only | Insight quality is the demo. Cost is roughly $1 to $2 a day. |
| Access | No SSO. Unguessable URL, `noindex`, rate limits on the Brian endpoint | Per the brief. The only thing worth protecting is our API spend. |

## Part 1: getting the data

I tested every source I could reach without a new key this afternoon. The status column says what was tested and what is still a logical guess.

The cadences below are the target. Current setting (Joe, 30 September): X every 15 minutes, everything else once a day, to be raised when the pitch cadence is agreed.

| # | Source | How we fetch it | Cadence | Cost | Key needed | Status |
|---|---|---|---|---|---|---|
| 1 | Martin Lewis on X (@MartinSLewis, id 252569527) | X API v2 `GET /2/users/:id/tweets` with `since_id`, the code already in `fetch_tweets.py` | Every 15 min | $0.005 per tweet returned. Roughly $10 to $20 a month including engagement refreshes, plus about $5 once for a 1,000-tweet backfill | Have it | Tested today (5 tweets pulled) |
| 2 | MoneySavingExpert on X (@MoneySavingExp) | Same script, second handle | Every 15 min | As above | Have it | Same code, untested on this handle |
| 3 | Martin Lewis on Instagram (@martinlewismse) | EnsembleData `GET /apis/instagram/user/posts?username=` (1 unit per 10 posts). Same vendor and endpoint family as Cortex's Social Comment Analyser and ByteSights | Hourly (24 units a day) | Free trial gives 50 units a day, which covers this. Paid plan starts at $100 a month if we want comments too | EnsembleData token (own trial) | Vendor pricing and endpoints confirmed. Call untested |
| 4 | MSE news | RSS at `moneysavingexpert.com/news/feeds/news.rss` (20 items, title, link, date, image). On each new item, fetch the article page for text and category | Every 30 min | Free | None | Tested. Feed and article pages both return 200 from Python |
| 5 | MSE guide pages (car, home, pet and travel insurance, utilities, credit cards) | Fetch each page, strip navigation, hash the main content. When the hash changes, store a diff as a "guide updated" event | Every 2 hours | Free | None | Page fetch tested (200). Diffing untested |
| 6 | MSE forum | Vanilla Forums public JSON API: `forums.moneysavingexpert.com/api/v2/discussions?categoryID=21&sort=-dateLastComment&limit=100`. Boards: Insurance & life assurance (21), Energy (13), Techie Stuff (29), plus Broadband (69), Credit cards (11), Pets (143) | Hourly | Free | None | Tested. Returns titles, bodies, comment and view counts |
| 7 | National press | Google News RSS (`news.google.com/rss/search?q="Martin Lewis"&hl=en-GB&gl=GB&ceid=GB:en`) plus Bing News RSS for a second net. Publisher name comes with each item | Hourly | Free | None | Both tested and returning fresh Martin Lewis stories |
| 8 | Google Trends (6 GB queries) | Decodo Web Scraping API, `google_trends_explore` target, one request per query with `geo: GB`. Six requests a day for the 90-day view. During a spike, hourly requests for the affected term over 7 days | Daily, hourly during a spike | Decodo's free plan includes 2,000 requests, then Starter at $19 a month. We need roughly 200 to 400 a month | Decodo scraper username and password (have them) | Tested and working: returns interest over time (weekly across 12 months, or daily inside a `date_start`/`date_end` window), a region breakdown and related queries. One problem: every `geo` value is rejected with a validation error, including the vendor's own `US` example, so the series is worldwide rather than GB. See Part 7 |
| 9 | YouTube (Martin's channel and Money Show clips) | YouTube Data API v3: uploads playlist `UU5CDoveqvEuQsW3x-DnYtww`, `videos.list` for view counts, `commentThreads.list` for top comments. Transcripts through `youtube-transcript-api` so Brian can read what he said | Twice daily | Free (10,000 quota units a day, we use under 100) | Google Cloud API key (have it) | Key tested: channel lookup returned the Martin Lewis channel, 226k subscribers, 430 videos. Transcript library is unofficial |
| 10 | Reddit (r/UKPersonalFinance, r/AskUK) | EnsembleData `reddit/subreddit/posts` (newest, three pages a subreddit), kept when a post mentions Martin or MSE or matches a CTM topic. Its keyword-search endpoint does not exist | Daily for now | About 12 Ensemble units a day, inside the trial | EnsembleData token (have it) | Built and tested 30 September: 21 posts on the first pull |

### Notes on the awkward ones

**X.** The current script excludes replies, which also drops the second and third tweets of Martin's own threads. The poller should include replies and keep only those where `in_reply_to_user_id` is his own id. Engagement changes are the interesting part for CTM, so re-read each tweet's `public_metrics` at 1, 6 and 24 hours after posting (three reads a tweet, about 1.5p). One thing to verify in week one: whether a poll that returns nothing new is billed. Third-party write-ups say X bills per tweet returned, not per request, but I have not confirmed that with X's own pricing page.

**Instagram.** The Meta Graph API only reads other accounts through Business Discovery, which needs a Facebook Page, an Instagram business account and a Meta app. Days, not hours. EnsembleData does it with one GET, and Brainlabs already runs three consumers of it in production, so the response shape is known (see `Project-X/apps/sandbox/services/sandbox/sandbox/api/apps/social_comment_analyser/services/`). Do not borrow the company token: it was the subject of a security hardening ticket yesterday and asking would slow us down. A trial account on Joe's email gives 50 units a day. Fallback if the trial refuses the account: Apify's `instagram-scraper` actor, which a previous Brainlabs vibe-code build used.

**MSE.** Two corrections to the source table. The `/latest-news/` URL is a 404; the section is `/news/`. And MSE does publish RSS, at `/news/feeds/news.rss`, but the items carry no summary or category, so we fetch each article once to get the text. MSE sits behind Cloudflare, which rejected `curl` outright but accepted Python with a browser User-Agent. Railway's datacentre IP might be treated more harshly than my laptop, so test on the first deploy. The fallback is a headless browser container or a scraping API at about $49 a month.

**Google Trends.** Google announced an official Trends API in July 2025, but it is still an application-gated alpha. Apply anyway (it is free), and use Decodo's Web Scraping API in the meantime. Joe chose Decodo over SerpApi on 30 September. Decodo's `google_trends_explore` target returns the interest-over-time series as parsed JSON, plus region breakdown and related queries, and it honours `date_start` and `date_end` (daily points for a 7-day window). What it will not currently do is scope to the UK: `geo` fails validation with every value we tried, twenty-odd requests' worth, including the vendor's own example. For UK-specific phrases such as "energy price cap" the worldwide series is close to the GB one anyway (the UK tops the region breakdown), but for generic phrases such as "pet insurance cost" the US would dominate. Decodo also offers Reddit and YouTube targets, including YouTube subtitles, which gives us a second route for two other sources if we ever want one vendor for all three. The unofficial `pytrends` library is the popular answer online and it is contradicted by reality: it is rate-limited and blocked often enough that I would not put it in front of a client.

**Press.** The table proposed Meltwater or Infegy. Brainlabs does hold Infegy, but under other clients' contracts (it appears in the UUSA statements of work), and Google News RSS already returns the Mirror, Metro, Express, Yahoo and regional titles for free. Not worth the ask for a pitch.

**Reddit.** Built on EnsembleData in the end, because we already hold the token and the daily cadence keeps it to about 12 units a day alongside Instagram. If we go back to hourly polling, switch to the official Reddit API (free, needs a script app) or Decodo's Reddit targets; the module is 60 lines either way. If we later pay for EnsembleData, move Reddit and YouTube onto it and drop two keys.

## Part 2: hosting and plumbing

### The shape

One Python service does everything: runs the pollers on a schedule, writes to SQLite, serves the JSON API, serves the UI, and hosts Brian's endpoints. Railway runs it as a single always-on container with a 1 GB volume mounted at `/data`.

```
martin-monitor/
  app/
    main.py            FastAPI app: /api/*, static UI, /health
    scheduler.py       APScheduler jobs built from sources.yaml
    db.py              SQLite schema and helpers
    sources/           one small module per source (x.py, instagram.py, mse_news.py,
                       mse_guides.py, mse_forum.py, press.py, trends.py, youtube.py, reddit.py)
    brian/
      insights.py      scheduled pass: new signals in, structured insights out
      ask.py           live Q&A endpoint (streaming)
      context.md       what Brian knows about CTM's business (we write this together)
  ui/                  index.html, app.js, styles.css (tokens copied from ctm-dashboard)
  sources.yaml         handles, URLs, query terms, cadences
  Dockerfile, .env.example, README.md   (Railway settings live in its dashboard; config-as-code is deprecated)
```

Every source module has the same contract: `fetch(since) -> list[Item]`. The scheduler calls it, dedupes on `(source, external_id)`, stores new rows, records the run. Adding a source later is one file and one line in `sources.yaml`.

### Data model

Five tables, all in SQLite.

- `items`: one row per post, article, thread, video, press story or guide change. Columns: `source`, `kind`, `external_id`, `author`, `title`, `text`, `url`, `published_at`, `first_seen_at`, `metrics_json`, `topics_json`, `raw_json`.
- `metric_snapshots`: `item_id`, `captured_at`, likes, reposts, replies, views, comments. Gives us velocity, which is the number CTM cares about.
- `trends`: `term`, `captured_at`, `value`, `geo`.
- `insights`: Brian's output. `headline`, `body`, `impact_json` (product line, direction, expected size, timing window), `actions_json`, `confidence`, `evidence_item_ids`, `model`, `created_at`.
- `runs`: `source`, `started_at`, `ok`, `items_new`, `error`. Drives the health strip in the UI.

Topics are CTM product categories (car insurance, home insurance, pet insurance, travel insurance, energy, broadband, credit cards). A keyword pass tags each item on arrival; Brian corrects the tags in his hourly pass.

### API

`GET /api/summary` (counts, latest per source, health), `GET /api/feed?since=&source=&topic=`, `GET /api/trends`, `GET /api/insights`, `GET /api/items/{id}`, `POST /api/brian/ask` (server-sent events). The UI is the only client, so no versioning.

### Deploying

The repo is `github.com/Joe-brainlabs/Martin-Monitor`, connected to Railway project `21d74822-bd4b-496a-8c21-2cf64acfbf96`. Railway builds from the Dockerfile on every push, so deploying is `git push`. Secrets live in Railway's environment variables and nowhere else. The volume holds `/data/martin.db`; a nightly job writes `/data/export.json` and copies it to a Google Cloud Storage bucket, so losing the volume costs us a day, not the project.

### What I ruled out, and why

- **Cloud Run + Cloud Scheduler + Firestore.** Google-native, which suits Brainlabs, but three services instead of one, and a scheduler inside a scale-to-zero container needs min-instances and always-on CPU anyway. Pick this only if Joe would rather stay inside Google Cloud.
- **GitHub Actions on a cron + GitHub Pages.** Free and tempting, but scheduled Actions routinely run 10 to 30 minutes late under load, and there is no server for Brian to answer live questions from.
- **n8n on the company account.** Would do the polling well, but it is the approvals path we are avoiding.
- **Brainlabs Sites.** Static pages only, so it cannot run the pollers, and open-internet publishing there needs the SSO-gated sharing flow. It still has a role: the CTM dashboard on Sites already reserves a "Martin Monitor" page with an empty data file (`ctm-dashboard/src/data/martin-monitor.json`). That page becomes an iframe of the live app, so the pitch flows from one place.
- **Notion.** Cannot run code or host an app. A Notion page can embed the live URL if that is useful for internal sharing.

## Part 3: the UI

Desktop first, because it will be shown on a meeting-room screen. Same visual language as the CTM dashboard: Figtree, the blue/navy/purple tokens from `ctm-dashboard/src/styles/tokens.css`, sentence case, British English. The Brian avatar, the star and the purple tint mark AI-generated content and nothing else, which is the dashboard's own rule and worth keeping.

From top to bottom:

1. **Top bar.** Martin Monitor wordmark, CTM logo, a live pulse ("Updated 3 minutes ago"), and one dot per source showing green or amber from the `runs` table.
2. **Hero panel** on the navy-to-purple Brian gradient. Brian's avatar, "Brian's read of the last 24 hours" as one generated paragraph, and three tiles: Martin posts today, categories in play (chips), loudest signal (for example "Energy price cap: 4 sources, forum activity up 180%").
3. **Signal feed** (left two thirds). One timeline across every source, newest first. Each card shows the source icon and author, time since posting, the text or headline, engagement with a velocity arrow, topic chips and a link out. Filters by source and by CTM category. When the same topic appears on Martin's X, then MSE, then the press within 48 hours, the cards get a small chain marker showing the story moving from first signal to official to mainstream.
4. **Brian's Insights** (right third). A stack of insight cards. Each one has a headline, what happened (with evidence links back to feed items), what consumers are likely to do next, the impact on CTM (product line, direction, expected size, timing window such as "next 24 to 72 hours"), a confidence level, and suggested actions as a short checklist (bids, budgets, creative, SEO or PR). Under the stack sits **Ask Brian**: a chat box with three suggested questions and streamed answers.
5. **Demand panel.** Google Trends lines for the six queries over 90 days, with markers where Martin's posts landed. Zoom to 7-day hourly view during a spike. The point of the chart is the visible gap between a post and the search response.
6. **Where it is spreading.** Small multiples: forum threads and comment velocity per board, press pickup by publisher, Reddit posts and upvotes, YouTube views.
7. **Footer.** Freshness and last-run status per source, and the model name behind Brian.

Charts get built with the `dataviz` skill and the dashboard's chart conventions. Branding decided on 30 September: the client-facing page carries CTM's look, since it lives inside their pitch dashboard. Still open: whether we want a custom domain or the Railway URL is fine for the pitch.

## Part 4: Brian's Insights, and whether Brian can call Claude live

Yes, Brian can call Claude in the live environment, and he should do it in two ways.

**Scheduled insights.** Every hour, and immediately when a new Martin or MSE post arrives, the service builds a context pack: new items since the last pass, the week's top items by engagement, trend deltas, forum velocity, and `brian/context.md`, which holds what Brian knows about CTM (product lines, how a Martin Lewis call moves switching demand and auction prices, seasonality, the competitor set). Claude Opus 5.5 returns insights against a JSON schema using structured outputs, so every card has the same fields and nothing needs parsing. The stable system prompt and context file are cached, so each pass costs about 3 to 5 cents. If nothing new arrived, Brian only refreshes the "read of the day" every six hours.

**Ask Brian, live.** The browser posts a question to `/api/brian/ask`. The server assembles the same cached system prompt, the latest summary and the items that match the question (keyword retrieval from SQLite is enough at this size), calls `client.messages.stream`, and relays the tokens to the page as server-sent events. Roughly 3 to 8 cents a question.

Rules that keep this safe with no login on the page:

- The Anthropic key lives only in Railway's environment. The browser never sees it, and there is no direct-to-Anthropic call from the page.
- Per-IP rate limit on the ask endpoint (20 an hour), a cap on question length, `max_tokens` around 1,500, and a monthly spend limit set in the Anthropic console.
- Every Brian output carries the avatar, a confidence level and its evidence links, so the client can check him. He also says when he has no evidence.
- Optional and off by default: give Brian the `web_search` server tool for questions like "what has Ofgem announced". It makes answers better and costs less predictable, so we turn it on only for the demo.

Expected Brian spend at pitch usage: about $30 to $60 a month.

## Part 5: build order

Each phase leaves something you can show.

| Phase | Time | What gets built | Demoable result |
|---|---|---|---|
| 0 | Done 30 Sep | Repo skeleton, SQLite, scheduler, pollers for all eight sources (X, Instagram, MSE news, MSE forum, press, YouTube, Trends, guide changes), feed page, Dockerfile and Railway config. First run stored 33 tweets, 10 Instagram posts, 20 articles, 300 threads, 104 press stories, 25 videos and 504 trend points | A live feed from every source on Joe's laptop, ready to deploy |
| 1 | Done 30 Sep, bar the production backfill | Railway deploy with volume and health checks (Joe). Reddit poller. X engagement re-reads at 1, 6 and 24 hours. Backfill endpoints behind the admin token for X and Instagram; MSE news and press already reach back a month from their feeds | The same feed on a public URL, updating itself; history once the backfill commands are run |
| 2 | One day | The real UI: hero, feed with filters and chain markers, demand chart, spread panel, CTM tokens. Iframe into the CTM dashboard's Martin Monitor page | The page you would show a client |
| 3 | One day | Brian: `context.md` written with Joe, scheduled insights with the schema, Ask Brian streaming, prompt tuning against the backfilled month | Brian reading real signals and answering questions live |
| 4 | Half a day | Polish, freshness indicators, spend caps, security pass with `bl-vibe-code-security-guardrails`, README, Vibe Coding Log entry | Ready for the pitch |

Four days of build, five with slack. Phase 0 can start before any key arrives.

## Part 6: what Joe needs to get

In the order we need them.

| # | Account or key | Where | Time | Cost | Used for |
|---|---|---|---|---|---|
| 1 | X API credits top-up | console.x.com, billing | Done, may need $20 to $30 more | See Part 1 | Sources 1 and 2, plus the backfill |
| 2 | Anthropic API key, with a monthly spend limit set (suggest $100) | platform.claude.com | 5 min | Usage, about $30 to $60 a month | Brian |
| 3 | Railway account, connected to GitHub | Done. Project id `21d74822-bd4b-496a-8c21-2cf64acfbf96` | Done | $5 Hobby plan plus usage, about $5 to $10 a month | Hosting |
| 4 | GitHub repo | Done. `github.com/Joe-brainlabs/Martin-Monitor` (remote `origin` in this folder) | Done | Free | Code and deploys |
| 5 | EnsembleData free trial token | Done (30 Sep) | Done | Free (50 units a day). $100 a month only if we add comments | Instagram |
| 6 | Google Cloud API key with YouTube Data API v3 enabled | Done. The key is from the "Anomaly Checker" project in Joe's Google Cloud console | Done | Free | YouTube |
| 7 | Reddit "script" app | Not needed for now: Reddit runs on the EnsembleData token | | Free | Reddit, only if we return to hourly polling |
| 8 | Decodo Web Scraping API key | decodo.com dashboard | Done | Plan on Joe's account | Google Trends |
| 9 | Optional: apply for the Google Trends API alpha | developers.google.com/search/apis/trends | 5 min to apply, weeks to hear back | Free | Replaces Decodo for Trends if granted |

Not needed: Meltwater, Infegy, a Meta developer app, or anyone else's tokens.

Put every key in `.env` locally (already gitignored) and in Railway's variables for production. Nothing else stores them.

## Part 7: verify in week one

- **X billing on empty polls.** Watch the credit balance across a day of 15-minute polls. If empty polls cost money, drop to 30 minutes.
- **EnsembleData trial.** Confirm the trial accepts a Brainlabs email and that `instagram/user/posts` returns for @martinlewismse.
- **MSE from Railway.** Checked on the first deploy (30 September): Cloudflare returns 403 to Railway's IP for article and guide pages, while the RSS feed and forum API pass. Fixed by fetching refused pages through Decodo's universal target (residential IPs), roughly ten requests a day.
- **YouTube transcripts.** The library is unofficial. If it breaks, Brian reads titles and descriptions and we lose little.
- **Decodo geo.** Ask Decodo support (live chat in the dashboard) why `geo` is rejected on `google_trends_explore` when their own example uses it. Send them the failing request: `{"target":"google_trends_explore","query":"energy price cap","geo":"GB"}` returns 400 Validation failed, and the same body without `geo` returns 200. Decided 30 September: we go global. The Trends module stores Decodo's worldwide series, and the chart labels it as worldwide so nobody mistakes it for UK-only. The query set leans on UK-specific phrasing to keep the lines meaningful. The module still takes a provider switch in case Decodo fixes `geo` or we want SerpApi later. Hourly granularity is also unconfirmed: Decodo returned daily points for a 7-day window.

## Running cost

| Item | Monthly |
|---|---|
| X API | $10 to $20, plus about $5 once for the backfill |
| Anthropic (Brian) | $30 to $60 |
| Railway | $5 to $10 |
| EnsembleData, YouTube, Reddit, RSS feeds | $0 on free tiers |
| Decodo (Google Trends) | $0 inside the free plan's 2,000 requests, then $19 Starter. Usage is a few hundred requests a month |
| **Total** | **About $45 to $90** |

If the Instagram trial runs out, the paid EnsembleData plan adds $100 and lets us move Reddit and YouTube onto it too.

## Appendix: what changed from the source table

- MSE news URL corrected to `/news/`, and the real RSS feed found at `/news/feeds/news.rss`.
- MSE pet insurance guide URL corrected to `/insurance/cut-pet-insurance-costs/` (the one in the table is a 404).
- Instagram through EnsembleData rather than Infegy.
- National press through Google News and Bing RSS rather than Meltwater or Infegy.
- Google Trends through Decodo's Web Scraping API (Joe's choice over SerpApi), with an alpha application in the background.
- Cadences: X stays at 15 minutes as specified. Everything else defaults to hourly, guide pages to two-hourly, Trends to daily with hourly zoom during a spike.
- Added: Martin's own reply threads on X, engagement re-reads for velocity, and MSE guide-page change detection as its own event type.
