"""Shared helpers: paths, HTTP, CSV and HTML link extraction. Standard library only."""

import csv
import gzip
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WATCHLIST = DATA / "watchlist.csv"
SNAPSHOTS = DATA / "snapshots"
DIGESTS = ROOT / "digests"
DOCS = ROOT / "docs"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36 vc-dealflow-tracker"
)

WATCHLIST_FIELDS = [
    "company_id", "company", "category", "map_status", "website",
    "linkedin_url", "linkedin_source",
    "github_org", "github_source",
    "careers_url", "jobs_source", "jobs_source_ref",
    "news_terms",
]


def http_get(url, headers=None, timeout=20, retries=2):
    """GET a URL and return (status, final_url, text). Raises on network failure."""
    hdrs = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip", "Accept-Language": "en,el;q=0.8"}
    hdrs.update(headers or {})
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.status, resp.geturl(), raw.decode(charset, errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503, 504) and attempt < retries:
                time.sleep(2 * (attempt + 1))
                last_err = e
                continue
            return e.code, url, ""
        except Exception as e:  # DNS, TLS, timeouts
            last_err = e
            if attempt < retries:
                time.sleep(1 + attempt)
    raise last_err


def http_json(url, headers=None, timeout=20):
    status, _, text = http_get(url, headers=headers, timeout=timeout)
    if status != 200 or not text:
        return status, None
    try:
        return status, json.loads(text)
    except json.JSONDecodeError:
        return status, None


def github_token():
    """GITHUB_TOKEN from the environment, else the token of a logged-in gh CLI."""
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    if shutil.which("gh"):
        try:
            out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
            return out.stdout.strip() or None
        except Exception:
            return None
    return None


def clean_url(value):
    """The market map stores notes after some URLs, e.g. 'https://x.com/ (redirects to ...)'."""
    value = (value or "").strip()
    return value.split()[0] if value else ""


def domain_of(url):
    host = urllib.parse.urlparse(url if "//" in url else "https://" + url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def read_watchlist():
    with open(WATCHLIST, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_watchlist(rows):
    with open(WATCHLIST, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=WATCHLIST_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None


def extract_links(html, base_url):
    """Return [(absolute_href, anchor_text)] for every <a> in the page."""
    p = _LinkParser()
    try:
        p.feed(html)
    except Exception:
        pass
    out = []
    for href, text in p.links:
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        out.append((urllib.parse.urljoin(base_url, href), text))
    return out
