"""Weekly momentum score.

Week score: points for this week's changes, each signal capped so no single one dominates.

    funding headline     5 each, max 10
    EU grant signed      3 each, max 6
    other press          1 each, max 3
    new role             1 each, max 5
    commits (non-bot)    1 for 1-4, 2 for 5-19, 3 for 20 or more (all repos together)
    new public repo      1 each, max 2
    stars gained         1 per 25, max 2

Momentum: the week score plus decayed earlier weeks, 1 + 0.5 + 0.25 + 0.125 over the last
four weekly runs. History is kept in data/scores.csv, one row per company per run.
"""

import csv
from collections import defaultdict

from .common import DATA

SCORES = DATA / "scores.csv"
FIELDS = ["date", "company_id", "company", "week_score", "funding", "grants", "press", "hiring", "github"]
DECAY = [1.0, 0.5, 0.25, 0.125]


def commit_points(n):
    return 0 if n <= 0 else 1 if n < 5 else 2 if n < 20 else 3


def week_scores(changes, rows):
    """{company_id: {"week_score", "funding", "press", "hiring", "github"}} for every company."""
    by = defaultdict(lambda: defaultdict(int))
    for c in changes:
        by[c["company_id"]][c["kind"]] += c.get("count", 1)
    out = {}
    for r in rows:
        k = by[r["company_id"]]
        parts = {
            "funding": min(10, 5 * k["funding"]),
            "grants": min(6, 3 * k["grant"]),
            "press": min(3, k["press"]),
            "hiring": min(5, k["new_role"]),
            "github": commit_points(k["commits"]) + min(2, k["new_repo"]) + min(2, max(0, k["stars"]) // 25),
        }
        out[r["company_id"]] = {"week_score": sum(parts.values()), **parts}
    return out


def _read_history():
    if not SCORES.exists():
        return []
    with open(SCORES, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def update(date, changes, rows):
    """Save this run's week scores (replacing a same-day run) and return ranked movers."""
    scores = week_scores(changes, rows)
    history = [h for h in _read_history() if h["date"] != date]
    history += [{"date": date, "company_id": r["company_id"], "company": r["company"], **scores[r["company_id"]]}
                for r in rows]
    history.sort(key=lambda h: (h["date"], h["company_id"]))
    with open(SCORES, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(history)

    dates = sorted({h["date"] for h in history if h["date"] <= date}, reverse=True)[:len(DECAY)]
    weight = {d: DECAY[i] for i, d in enumerate(dates)}
    momentum, prev_week = defaultdict(float), {}
    for h in history:
        if h["date"] in weight:
            momentum[h["company_id"]] += weight[h["date"]] * float(h["week_score"])
        if len(dates) > 1 and h["date"] == dates[1]:
            prev_week[h["company_id"]] = float(h["week_score"])

    movers = []
    for r in rows:
        s = scores[r["company_id"]]
        movers.append({
            "company_id": r["company_id"], "company": r["company"], "category": r["category"],
            "greek_funds": [f for f in r.get("greek_funds", "").split(" | ") if f],
            "greek_fund_status": r.get("greek_fund_status", ""),
            "week_score": s["week_score"], "momentum": round(momentum[r["company_id"]], 2),
            "last_week": prev_week.get(r["company_id"]),
            "parts": {k: s[k] for k in ("funding", "grants", "press", "hiring", "github")},
        })
    movers.sort(key=lambda m: (-m["momentum"], -m["week_score"], m["company"]))
    for i, m in enumerate(movers, 1):
        m["rank"] = i
    return movers, len(dates)
