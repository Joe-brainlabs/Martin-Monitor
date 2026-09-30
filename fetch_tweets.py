"""Download Martin Lewis's (@MartinSLewis) tweets via the X API v2.

Usage:
    python3 fetch_tweets.py                 # fetch new tweets since last run
    python3 fetch_tweets.py --max 200       # cap how many tweets to pull this run
    python3 fetch_tweets.py --user someone  # different handle
    python3 fetch_tweets.py --user-id 123   # skip the username -> ID lookup

Tweets are appended to data/<handle>.jsonl (one JSON object per line).
Re-running only fetches tweets newer than the latest one already saved.
"""

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.x.com/2"
ROOT = Path(__file__).parent
TWEET_FIELDS = "created_at,public_metrics,conversation_id,in_reply_to_user_id,referenced_tweets,entities,lang"


def load_env(path=ROOT / ".env"):
    env = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def get(path, token, params=None):
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    while True:
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                reset = int(e.headers.get("x-rate-limit-reset", time.time() + 60))
                wait = max(reset - int(time.time()), 1) + 1
                print(f"Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            raise SystemExit(f"HTTP {e.code} from {path}: {e.read().decode()}")


def lookup_user_id(username, token, cache_path=ROOT / "data" / "user_ids.json"):
    """Resolve a handle to its numeric ID, caching it so we only pay for the lookup once."""
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    if username.lower() not in cache:
        cache[username.lower()] = get(f"/users/by/username/{username}", token)["data"]["id"]
        cache_path.write_text(json.dumps(cache, indent=2) + "\n")
    return cache[username.lower()]


def latest_saved_id(out_path):
    if not out_path.exists():
        return None
    ids = [int(json.loads(line)["id"]) for line in out_path.read_text().splitlines() if line]
    return str(max(ids)) if ids else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default="MartinSLewis")
    parser.add_argument("--user-id", help="numeric account ID; skips the username lookup")
    parser.add_argument("--max", type=int, default=3200, help="max tweets to fetch this run (API limit is ~3200)")
    parser.add_argument("--include-replies", action="store_true")
    parser.add_argument("--include-retweets", action="store_true")
    args = parser.parse_args()

    token = urllib.parse.unquote(load_env()["BEARER_TOKEN"])

    (ROOT / "data").mkdir(exist_ok=True)
    user_id = args.user_id or lookup_user_id(args.user, token)
    print(f"Fetching tweets for @{args.user} (id {user_id})")

    out_path = ROOT / "data" / f"{args.user}.jsonl"
    since_id = latest_saved_id(out_path)

    params = {"max_results": 100, "tweet.fields": TWEET_FIELDS}
    exclude = [x for x, keep in (("replies", args.include_replies), ("retweets", args.include_retweets)) if not keep]
    if exclude:
        params["exclude"] = ",".join(exclude)
    if since_id:
        params["since_id"] = since_id
        print(f"Only fetching tweets newer than {since_id}")

    tweets = []
    while len(tweets) < args.max:
        params["max_results"] = max(5, min(100, args.max - len(tweets)))
        page = get(f"/users/{user_id}/tweets", token, params)
        tweets.extend(page.get("data", []))
        print(f"  {len(tweets)} tweets so far")
        next_token = page.get("meta", {}).get("next_token")
        if not next_token:
            break
        params["pagination_token"] = next_token

    tweets = tweets[: args.max]
    # Write oldest first so the file stays in chronological order across runs
    with out_path.open("a") as f:
        for tweet in sorted(tweets, key=lambda t: int(t["id"])):
            f.write(json.dumps(tweet, ensure_ascii=False) + "\n")

    print(f"Saved {len(tweets)} new tweets to {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
