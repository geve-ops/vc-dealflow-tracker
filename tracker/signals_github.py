"""Public GitHub activity for companies with a github_org: repos, stars, and commits in the window."""

import time

from .common import http_json

API = "https://api.github.com"


def _headers(token):
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def collect(row, token, since_iso):
    org = row.get("github_org", "").strip()
    if not org or org == "none":
        return None
    hdr = _headers(token)
    st, repos = http_json(f"{API}/users/{org}/repos?type=owner&sort=pushed&per_page=100", headers=hdr)
    if st != 200 or repos is None:
        return {"org": org, "error": f"GitHub API HTTP {st}", "repos": []}
    out = []
    for r in repos:
        item = {
            "name": r["name"],
            "url": r["html_url"],
            "description": (r.get("description") or "")[:200],
            "created_at": r["created_at"],
            "pushed_at": r.get("pushed_at") or "",
            "stars": r.get("stargazers_count", 0),
            "fork": r.get("fork", False),
            "archived": r.get("archived", False),
        }
        # Commits only for repos pushed inside the window; one request each.
        if item["pushed_at"] >= since_iso and not item["fork"]:
            st, commits = http_json(
                f"{API}/repos/{org}/{r['name']}/commits?since={since_iso}&per_page=100", headers=hdr)
            if st == 200 and commits:
                item["window_commits"] = len(commits)
                item["window_commits_capped"] = len(commits) == 100
                item["latest_commit"] = {
                    "url": commits[0]["html_url"],
                    "message": (commits[0]["commit"]["message"] or "").splitlines()[0][:140],
                    "date": commits[0]["commit"]["committer"]["date"],
                }
            time.sleep(0.2)
        out.append(item)
    return {"org": org, "url": f"https://github.com/{org}", "since": since_iso, "repos": out}
