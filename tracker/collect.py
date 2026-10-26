"""Run every signal for every watchlist company and save a dated snapshot in data/snapshots/."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from . import signals_github, signals_jobs, signals_news
from .common import SNAPSHOTS, github_token, read_watchlist


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def snapshot_paths():
    return sorted(SNAPSHOTS.glob("*.json"))


def previous_snapshot(before_date):
    """Latest snapshot from a day before `before_date` (YYYY-MM-DD), or None."""
    older = [p for p in snapshot_paths() if p.stem < before_date]
    if not older:
        return None
    return json.loads(older[-1].read_text(encoding="utf-8"))


def collect(signals=("github", "news", "jobs"), lookback_days=7):
    now = utc_now()
    today = now.date().isoformat()
    prev = previous_snapshot(today)
    window_start = prev["generated_at"] if prev else iso(now - timedelta(days=lookback_days))
    rows = read_watchlist()
    token = github_token()

    def run(row):
        out = {}
        if "github" in signals:
            out["github"] = signals_github.collect(row, token, window_start)
        if "news" in signals:
            out["news"] = signals_news.collect(row)
        if "jobs" in signals:
            out["jobs"] = signals_jobs.collect(row)
        return row["company_id"], out

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = dict(pool.map(run, rows))

    snap = {
        "generated_at": iso(now),
        "window_start": window_start,
        "previous_snapshot": prev["generated_at"] if prev else None,
        "signals": list(signals),
        "companies": results,
    }
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOTS / f"{today}.json"
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"snapshot: {path} (window from {window_start})")
    return path
