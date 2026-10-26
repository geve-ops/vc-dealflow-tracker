"""Fill linkedin_url, github_org, careers_url and the job-board source from public pages.

Rules, so every value has a source:
- LinkedIn and GitHub links are taken from the company's own website. The source column
  records the page they were found on.
- If the website has no GitHub link, a GitHub organisation found by name search is accepted
  only when its profile lists the company's website domain.
- Job boards (Workable, Lever, Greenhouse, Ashby, Recruitee, Breezy, Personio) are detected from links
  or embeds on the homepage or careers page, and confirmed by calling the board's public API.
Filled values are never overwritten unless --force is given, so manual corrections stick.
Set a column to "none" to record that a company has no usable source (e.g. careers page belongs
to a parent company); enrich then leaves it alone and collect skips it.
"""

import re
import time
import urllib.parse

from .common import (domain_of, extract_links, github_token, http_get, http_json,
                     read_watchlist, write_watchlist)

LINKEDIN_RE = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/(company|showcase)/([A-Za-z0-9\-_%.]+)", re.I)
GITHUB_RE = re.compile(r"https?://(?:www\.)?github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))(?=[/\"'?#\s]|$)", re.I)
GITHUB_RESERVED = {"about", "features", "pricing", "sponsors", "marketplace", "login", "join", "orgs",
                   "topics", "collections", "explore", "settings", "apps", "enterprise", "site", "security",
                   # site builders and themes whose GitHub links appear in page markup
                   "wix", "wordpress", "webflow", "framer", "hubspot", "squarespace", "shopify",
                   "elementor", "vercel", "twbs", "jquery", "google", "facebook", "w3c"}

ATS_PATTERNS = [
    ("workable", re.compile(r"apply\.workable\.com/(?!api\b|j/)([a-z0-9][a-z0-9-]+)", re.I)),
    ("workable", re.compile(r"https?://(?!apply\.|www\.)([a-z0-9][a-z0-9-]+)\.workable\.com", re.I)),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9][A-Za-z0-9-]+)", re.I)),
    ("greenhouse", re.compile(r"(?:job-)?boards(?:\.eu)?\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=)?([A-Za-z0-9][A-Za-z0-9-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9][A-Za-z0-9.%-]+)", re.I)),
    ("recruitee", re.compile(r"https?://([a-z0-9][a-z0-9-]+)\.recruitee\.com", re.I)),
    ("breezy", re.compile(r"https?://([a-z0-9][a-z0-9-]+)\.breezy\.hr", re.I)),
    ("personio", re.compile(r"https?://([a-z0-9][a-z0-9-]+)\.jobs\.personio\.(?:de|com)", re.I)),
]
CAREERS_WORDS = re.compile(r"\b(careers?|jobs?|join (?:us|the team|our team)|work with us|we.?re hiring|open (?:roles|positions)|vacanc|καριέρα|θέσεις εργασίας)\b", re.I)
CAREERS_HREF = re.compile(r"/(careers?|jobs|join(-us)?|work-with-us|vacancies|open-positions)(/|$|\?)", re.I)


def ats_api_ok(kind, slug):
    """True when the board's public API answers for this slug."""
    from .signals_jobs import fetch_ats
    try:
        return fetch_ats(kind, slug) is not None
    except Exception:
        return False


def find_ats(html):
    seen = []
    for kind, rx in ATS_PATTERNS:
        for m in rx.finditer(html):
            slug = m.group(1).rstrip(".")
            if (kind, slug) not in seen:
                seen.append((kind, slug))
    for kind, slug in seen:
        if ats_api_ok(kind, slug):
            return kind, slug
    return None


def github_owner(login, token):
    hdr = {"Accept": "application/vnd.github+json"}
    if token:
        hdr["Authorization"] = f"Bearer {token}"
    status, data = http_json(f"https://api.github.com/users/{login}", headers=hdr)
    return data if status == 200 else None


def search_github_org(name, site_domain, token):
    """Search GitHub organisations by name; accept one whose profile 'blog' is the company domain."""
    hdr = {"Accept": "application/vnd.github+json"}
    if token:
        hdr["Authorization"] = f"Bearer {token}"
    q = urllib.parse.quote(f"{name} type:org")
    status, data = http_json(f"https://api.github.com/search/users?q={q}&per_page=10", headers=hdr)
    if status != 200 or not data:
        return None
    for item in data.get("items", []):
        owner = github_owner(item["login"], token)
        time.sleep(0.3)
        if owner and owner.get("blog") and domain_of(owner["blog"]) == site_domain:
            return owner["login"], owner["blog"]
    return None


def enrich_one(row, token, force=False):
    site = row["website"]
    notes = []
    if not site:
        return ["no website"]
    try:
        status, final_url, html = http_get(site)
    except Exception as e:
        status, final_url, html = 0, site, ""
        notes.append(f"website unreachable ({type(e).__name__})")
    if status and status != 200:
        notes.append(f"website HTTP {status}")
    site_domain = domain_of(final_url or site)
    links = extract_links(html, final_url) if html else []

    if html and (force or not row["linkedin_url"]):
        m = LINKEDIN_RE.search(html)
        if m:
            slug = urllib.parse.unquote(m.group(2)).strip("/")
            row["linkedin_url"] = f"https://www.linkedin.com/{m.group(1).lower()}/{slug}/"
            row["linkedin_source"] = f"linked from company website {final_url}"

    if force or not row["github_org"]:
        found = None
        for m in GITHUB_RE.finditer(html or ""):
            login = m.group(1)
            if login.lower() in GITHUB_RESERVED:
                continue
            owner = github_owner(login, token)
            if owner:
                found = (owner["login"], f"linked from company website {final_url}")
                break
        if not found:
            hit = search_github_org(re.sub(r"\s*\(.*?\)", "", row["company"]), site_domain, token)
            if hit:
                found = (hit[0], f"GitHub org profile lists {hit[1]}")
        if found:
            row["github_org"], row["github_source"] = found

    if html and (force or not row["careers_url"]):
        cand = [h for h, t in links if CAREERS_HREF.search(urllib.parse.urlparse(h).path + "/")
                or CAREERS_WORDS.search(t or "")]
        cand = [h for h in cand if "linkedin.com" not in h]
        if not cand:
            for path in ("/careers", "/jobs"):
                try:
                    st, fu, _ = http_get(urllib.parse.urljoin(final_url, path), retries=0)
                except Exception:
                    continue
                if st == 200 and fu.rstrip("/") != final_url.rstrip("/"):
                    cand = [fu]
                    break
        if cand:
            row["careers_url"] = cand[0]

    if force or not row["jobs_source"]:
        hit = find_ats(html or "")
        if not hit and row["careers_url"]:
            try:
                st, _, chtml = http_get(row["careers_url"], retries=0)
                if st == 200:
                    hit = find_ats(chtml)
            except Exception:
                pass
        if hit:
            row["jobs_source"], row["jobs_source_ref"] = hit
        elif row["careers_url"]:
            row["jobs_source"], row["jobs_source_ref"] = "careers_page", row["careers_url"]
    return notes


def enrich(force=False, only=None):
    rows = read_watchlist()
    token = github_token()
    for row in rows:
        if only and row["company_id"] not in only:
            continue
        notes = enrich_one(row, token, force=force)
        print(f"{row['company_id']} {row['company'][:28]:28} li={'Y' if row['linkedin_url'] else '-'} "
              f"gh={row['github_org'] or '-':18} jobs={row['jobs_source'] or '-':12} {'; '.join(notes)}")
        write_watchlist(rows)  # save as we go
    return rows
