"""Compare the latest snapshot with the one before it and write the weekly digest and dashboard.

Outputs:
- digests/YYYY-MM-DD.md   the "what changed" digest, one line per change with its source link
- docs/index.html         static dashboard (works from disk or GitHub Pages)
- docs/changes.json       the same changes as data
"""

import json
from datetime import datetime, timedelta

from .collect import snapshot_paths
from .common import DIGESTS, DOCS, read_watchlist

SIGNAL_LABELS = {"funding": "Funding news", "jobs": "Hiring", "github": "GitHub activity", "press": "Other press"}


def _date(s):
    return (s or "")[:10]


def load_pair():
    paths = snapshot_paths()
    if not paths:
        raise SystemExit("No snapshot found. Run: python run.py collect")
    cur = json.loads(paths[-1].read_text(encoding="utf-8"))
    prev = json.loads(paths[-2].read_text(encoding="utf-8")) if len(paths) > 1 else None
    return cur, prev


def company_changes(row, cur, prev, window_start):
    cid = row["company_id"]
    c = cur["companies"].get(cid, {})
    p = (prev or {}).get("companies", {}).get(cid, {})
    out = []

    def add(signal, title, url, date="", detail=""):
        out.append({"company_id": cid, "company": row["company"], "category": row["category"],
                    "signal": signal, "title": title, "url": url, "date": _date(date), "detail": detail})

    # News: published inside the window and not already seen last time.
    news = c.get("news") or {}
    prev_ids = {i["id"] for i in (p.get("news") or {}).get("items", [])}
    for it in news.get("items", []):
        if it["published"] >= window_start and it["id"] not in prev_ids:
            add(it["kind"], it["title"], it["url"], it["published"], it["source"])

    # GitHub.
    gh = c.get("github") or {}
    pgh = p.get("github") or {}
    if gh and not gh.get("error"):
        prev_repos = {r["name"]: r for r in pgh.get("repos", [])} if pgh and not pgh.get("error") else None
        for r in gh["repos"]:
            is_new = (r["name"] not in prev_repos) if prev_repos is not None else r["created_at"] >= window_start
            if is_new:
                add("github", f"New public repo {r['name']}", r["url"], r["created_at"], r["description"])
            if r.get("window_commits"):
                n = f"{r['window_commits']}{'+' if r.get('window_commits_capped') else ''}"
                lc = r["latest_commit"]
                add("github", f"{n} commit{'s' if n != '1' else ''} to {r['name']}", lc["url"], lc["date"],
                    f"latest: {lc['message']}")
        if prev_repos is not None:
            delta = sum(r["stars"] - prev_repos[r["name"]]["stars"] for r in gh["repos"] if r["name"] in prev_repos)
            if delta:
                total = sum(r["stars"] for r in gh["repos"])
                add("github", f"{delta:+d} stars across repos (now {total})", gh["url"], cur["generated_at"])

    # Jobs.
    jobs = c.get("jobs") or {}
    pjobs = p.get("jobs") or {}
    if jobs and not jobs.get("error"):
        heuristic = " (careers page, heuristic)" if jobs["source"] == "careers_page" else ""
        if pjobs and not pjobs.get("error") and pjobs.get("source") == jobs["source"]:
            before = {j["id"] for j in pjobs["postings"]}
            now_ids = {j["id"] for j in jobs["postings"]}
            for j in jobs["postings"]:
                if j["id"] not in before:
                    add("jobs", f"New role: {j['title']}{heuristic}", j["url"], j["published"] or cur["generated_at"], j["location"])
            closed = [j for j in pjobs["postings"] if j["id"] not in now_ids]
            for j in closed:
                add("jobs", f"Role closed: {j['title']}{heuristic}", j["url"], cur["generated_at"], "no longer listed")
        else:
            # First run for this source: only postings dated inside the window count as new.
            for j in jobs["postings"]:
                if j["published"] and j["published"] >= window_start[:10]:
                    add("jobs", f"New role: {j['title']}", j["url"], j["published"], j["location"])
    return out


def company_status(row, cur):
    c = cur["companies"].get(row["company_id"], {})
    gh, jobs, news = c.get("github") or {}, c.get("jobs") or {}, c.get("news") or {}
    # Google News "when:90d" is loose, so the 90-day cut is applied here as well.
    cutoff = (datetime.fromisoformat(cur["generated_at"].replace("Z", "+00:00")) - timedelta(days=90)).strftime("%Y-%m-%d")
    funding = [i for i in news.get("items", []) if i["kind"] == "funding" and i["published"][:10] >= cutoff]
    repos = gh.get("repos", [])
    return {
        "company_id": row["company_id"], "company": row["company"], "category": row["category"],
        "map_status": row["map_status"], "website": row["website"], "linkedin_url": row["linkedin_url"],
        "github_org": row["github_org"], "careers_url": row["careers_url"],
        "jobs_source": jobs.get("source", ""), "jobs_error": jobs.get("error", ""),
        # Zero from the careers-page heuristic usually means the page renders roles with JavaScript.
        "open_roles": (len(jobs["postings"]) if jobs and not jobs.get("error")
                       and (jobs["postings"] or jobs["source"] != "careers_page") else None),
        "repos": len(repos), "stars": sum(r["stars"] for r in repos),
        "last_push": max((r["pushed_at"] for r in repos), default="")[:10],
        "github_error": gh.get("error", ""), "news_error": news.get("error", ""),
        "latest_funding": ({"title": funding[0]["title"], "url": funding[0]["url"],
                            "date": _date(funding[0]["published"]), "source": funding[0]["source"]}
                           if funding else None),
    }


def _md_escape(s):
    return (s or "").replace("[", "\\[").replace("]", "\\]").replace("|", "\\|")


def write_markdown(changes, statuses, cur, prev, path):
    start, end = _date(cur["window_start"]), _date(cur["generated_at"])
    by_signal = {k: [c for c in changes if c["signal"] == k] for k in SIGNAL_LABELS}
    n_companies = len({c["company_id"] for c in changes})
    L = [f"# Deal-flow digest, week ending {datetime.fromisoformat(end).strftime('%d %B %Y')}", ""]
    L.append(f"Window: {start} to {end} (UTC). Watchlist: {len(statuses)} companies from the Greek Deep Tech Market Map.")
    if not prev:
        L.append("")
        L.append("First run: there is no earlier snapshot, so news, new repos, commits and job postings are "
                 "limited to items dated inside the window. Star changes and closed roles start from next week.")
    L += ["", "## Summary", ""]
    for k, label in SIGNAL_LABELS.items():
        cos = len({c["company_id"] for c in by_signal[k]})
        L.append(f"- {label}: {len(by_signal[k])} item{'s' if len(by_signal[k]) != 1 else ''} across {cos} compan{'ies' if cos != 1 else 'y'}")
    L.append(f"- Companies with any change: {n_companies} of {len(statuses)}")
    for k, label in SIGNAL_LABELS.items():
        L += ["", f"## {label}", ""]
        items = by_signal[k]
        if not items:
            L.append("Nothing new this week.")
            continue
        for cname in sorted({c["company"] for c in items}):
            rows = sorted([c for c in items if c["company"] == cname], key=lambda c: c["date"], reverse=True)
            L.append(f"**{cname}** ({rows[0]['category']})")
            L.append("")
            for c in rows:
                detail = f" ({_md_escape(c['detail'])})" if c["detail"] else ""
                L.append(f"- {c['date']} · [{_md_escape(c['title'])}]({c['url']}){detail}")
            L.append("")
    # Coverage, so gaps are visible instead of silent.
    gh_cov = sum(1 for s in statuses if s["github_org"])
    jobs_api = sum(1 for s in statuses if s["jobs_source"] and s["jobs_source"] != "careers_page")
    jobs_page = sum(1 for s in statuses if s["jobs_source"] == "careers_page")
    L += ["## Coverage", "",
          f"- GitHub organisation known: {gh_cov} of {len(statuses)}",
          f"- Job postings from a job-board API: {jobs_api}; from a careers page (heuristic): {jobs_page}; "
          f"no jobs source: {len(statuses) - jobs_api - jobs_page}",
          f"- News searched for all {len(statuses)} (Google News, English and Greek)"]
    errs = [(s["company"], e) for s in statuses for e in (s["github_error"], s["jobs_error"], s["news_error"]) if e]
    if errs:
        L += ["", "Errors this run (signal skipped for that company):", ""]
        L += [f"- {n}: {e}" for n, e in errs]
    L.append("")
    path.write_text("\n".join(L), encoding="utf-8")


def write_dashboard(changes, statuses, cur, prev, history):
    DOCS.mkdir(exist_ok=True)
    payload = {"generated_at": cur["generated_at"], "window_start": cur["window_start"],
               "first_run": prev is None, "changes": changes, "companies": statuses, "history": history}
    (DOCS / "changes.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    template = (DOCS.parent / "tracker" / "dashboard_template.html").read_text(encoding="utf-8")
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    (DOCS / "index.html").write_text(template.replace("/*__DATA__*/null", data), encoding="utf-8")


def build():
    cur, prev = load_pair()
    rows = read_watchlist()
    window_start = cur["window_start"]
    changes = [ch for r in rows for ch in company_changes(r, cur, prev, window_start)]
    changes.sort(key=lambda c: (c["date"], c["company"]), reverse=True)
    statuses = [company_status(r, cur) for r in rows]
    DIGESTS.mkdir(exist_ok=True)
    path = DIGESTS / f"{_date(cur['generated_at'])}.md"
    write_markdown(changes, statuses, cur, prev, path)
    history = sorted((p.stem for p in DIGESTS.glob("*.md")), reverse=True)
    write_dashboard(changes, statuses, cur, prev, history)
    print(f"digest: {path} ({len(changes)} changes); dashboard: {DOCS / 'index.html'}")
    return path
