"""Backtest: did public GitHub activity rise before known funding rounds?

For every watchlist company with a GitHub organisation and a round dated to the month in the
market map dataset, count non-bot commits across the organisation's own (non-fork) repos in:

    before:   the 6 months before the round month
    baseline: the 6 months before that

and compare them. Only GitHub can be backtested: news feeds and job boards do not keep history.
Results go to data/backtest.csv and into the monthly briefing.
"""

import csv
import time
from datetime import date

from .briefing import round_month, stage_bucket, usd_millions
from .common import DATA, github_token, http_json, read_watchlist
from .signals_github import API, _headers, _is_bot

BACKTEST = DATA / "backtest.csv"
FIELDS = ["company_id", "company", "github_org", "round_month", "round", "repos_counted",
          "commits_baseline", "commits_before", "change", "capped"]
MAX_PAGES = 10  # 1,000 commits per repo per window; marked as capped beyond that
EARLIEST = (2021, 1)


def _shift(ym, months):
    y, m = ym
    total = y * 12 + (m - 1) + months
    return total // 12, total % 12 + 1


def _iso(ym):
    return f"{ym[0]:04d}-{ym[1]:02d}-01T00:00:00Z"


def _count(org, repo, since, until, hdr):
    """(non-bot commits, capped) in [since, until)."""
    n, page = 0, 1
    while page <= MAX_PAGES:
        st, commits = http_json(f"{API}/repos/{org}/{repo}/commits?since={since}&until={until}"
                                f"&per_page=100&page={page}", headers=hdr)
        if st != 200 or not commits:
            return n, False
        n += sum(1 for c in commits if not _is_bot(c))
        if len(commits) < 100:
            return n, False
        page += 1
        time.sleep(0.1)
    return n, True


def classify(base, before):
    if base == 0 and before == 0:
        return "no activity"
    if base == 0:
        return "rose (from zero)"
    ratio = before / base
    return "rose" if ratio >= 1.25 else "fell" if ratio <= 0.8 else "flat"


def run():
    hdr = _headers(github_token())
    today = date.today()
    out = []
    for r in read_watchlist():
        org = r["github_org"]
        ym = round_month(r["last_round_date"])
        bucket = stage_bucket(r["stage"], usd_millions(r["last_round_amount"]))
        if not org or org == "none" or not ym or ym < EARLIEST or bucket in ("Exited", "Non-venture"):
            continue
        if ym > (today.year, today.month):
            continue
        b0, b1, b2 = _shift(ym, -12), _shift(ym, -6), ym
        st, repos = http_json(f"{API}/users/{org}/repos?type=owner&per_page=100", headers=hdr)
        if st != 200 or repos is None:
            print(f"{r['company']}: GitHub HTTP {st}, skipped")
            continue
        repos = [x for x in repos if not x["fork"] and x["created_at"] < _iso(b2)
                 and (x.get("pushed_at") or "") >= _iso(b0)]
        base = before = 0
        capped = False
        for x in repos:
            n, c1 = _count(org, x["name"], _iso(b0), _iso(b1), hdr)
            m, c2 = _count(org, x["name"], _iso(b1), _iso(b2), hdr)
            base, before, capped = base + n, before + m, capped or c1 or c2
        row = {"company_id": r["company_id"], "company": r["company"], "github_org": org,
               "round_month": f"{ym[0]:04d}-{ym[1]:02d}", "round": r["last_round_amount"].split(" (")[0],
               "repos_counted": len(repos), "commits_baseline": base, "commits_before": before,
               "change": classify(base, before), "capped": capped}
        print(f"{row['company'][:28]:28} {row['round_month']} repos={len(repos):3} "
              f"baseline={base:5} before={before:5} {row['change']}")
        out.append(row)
    with open(BACKTEST, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    return out


def read():
    if not BACKTEST.exists():
        return []
    with open(BACKTEST, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
