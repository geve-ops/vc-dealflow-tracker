"""Job postings signal.

Structured sources (public job-board APIs, no key needed): Workable, Lever, Greenhouse, Ashby,
Recruitee, Breezy, Personio. Each returns a list of open postings with a link to the posting.
Fallback: the company's own careers page, where links that look like individual roles are
recorded. That fallback is a heuristic and is labelled as such in the digest.
"""

import re
import urllib.parse
import xml.etree.ElementTree as ET

from .common import extract_links, http_get, http_json


def _posting(pid, title, url, published="", location=""):
    return {"id": str(pid), "title": (title or "").strip(), "url": url,
            "published": published or "", "location": location or ""}


def fetch_ats(kind, slug):
    """Open postings for a job board, or None if the board does not answer."""
    if kind == "workable":
        st, d = http_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
        if st != 200 or d is None:
            return None
        return [_posting(j.get("shortcode"), j.get("title"), j.get("url") or j.get("shortlink"),
                         j.get("published_on") or j.get("created_at"),
                         ", ".join(x for x in (j.get("city"), j.get("country")) if x))
                for j in d.get("jobs", [])]
    if kind == "lever":
        st, d = http_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
        if st != 200 or d is None:
            st, d = http_json(f"https://api.eu.lever.co/v0/postings/{slug}?mode=json")
        if st != 200 or d is None:
            return None
        from datetime import datetime, timezone
        return [_posting(j["id"], j.get("text"), j.get("hostedUrl"),
                         datetime.fromtimestamp(j["createdAt"] / 1000, timezone.utc).date().isoformat()
                         if j.get("createdAt") else "",
                         (j.get("categories") or {}).get("location", ""))
                for j in d]
    if kind == "greenhouse":
        st, d = http_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
        if st != 200 or d is None:
            return None
        return [_posting(j["id"], j.get("title"), j.get("absolute_url"),
                         (j.get("first_published") or j.get("updated_at") or "")[:10],
                         (j.get("location") or {}).get("name", ""))
                for j in d.get("jobs", [])]
    if kind == "ashby":
        st, d = http_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        if st != 200 or d is None:
            return None
        return [_posting(j.get("id") or j.get("jobUrl"), j.get("title"), j.get("jobUrl"),
                         (j.get("publishedAt") or "")[:10], j.get("location", ""))
                for j in d.get("jobs", [])]
    if kind == "recruitee":
        st, d = http_json(f"https://{slug}.recruitee.com/api/offers/")
        if st != 200 or d is None:
            return None
        return [_posting(j["id"], j.get("title"), j.get("careers_url"),
                         (j.get("published_at") or "")[:10], j.get("location", ""))
                for j in d.get("offers", [])]
    if kind == "breezy":
        st, d = http_json(f"https://{slug}.breezy.hr/json")
        if st != 200 or d is None:
            return None
        return [_posting(j.get("id"), j.get("name"), j.get("url"), (j.get("published_date") or "")[:10],
                         (j.get("location") or {}).get("name", "") if isinstance(j.get("location"), dict) else "")
                for j in d]
    if kind == "personio":
        for tld in ("de", "com"):
            st, _, text = http_get(f"https://{slug}.jobs.personio.{tld}/xml")
            if st == 200 and text.strip().startswith("<"):
                root = ET.fromstring(text.encode("utf-8"))
                return [_posting(p.findtext("id"), p.findtext("name"),
                                 f"https://{slug}.jobs.personio.{tld}/job/{p.findtext('id')}",
                                 (p.findtext("createdAt") or "")[:10], p.findtext("office") or "")
                        for p in root.iter("position")]
        return None
    return None


ROLE_WORDS = re.compile(
    r"\b(engineer|developer|scientist|manager|lead|head of|intern|analyst|specialist|designer|"
    r"architect|researcher|technician|officer|director|associate|consultant|administrator|"
    r"executive|operator|coordinator|representative|μηχανικ|προγραμματιστ)", re.I)
ROLE_HREF = re.compile(r"/(careers?|jobs?|positions?|openings?|vacanc\w*|roles?)/[^/?#]+", re.I)


def careers_page_postings(url):
    """Heuristic: links on the careers page whose text reads like a role title and whose URL
    looks like a single posting. Pages that render roles with JavaScript return nothing."""
    st, final_url, html = http_get(url)
    if st != 200:
        raise RuntimeError(f"careers page HTTP {st}")
    out, seen = [], set()
    for href, text in extract_links(html, final_url):
        if not text or len(text) > 120:
            continue
        path = urllib.parse.urlparse(href).path
        on_board = any(d in href for d in ("workable.com", "lever.co", "greenhouse.io", "ashbyhq.com",
                                            "recruitee.com", "breezy.hr", "personio.", "teamtailor.com"))
        if ROLE_WORDS.search(text) and (ROLE_HREF.search(path) or on_board):
            key = href.split("#")[0]
            if key in seen or "linkedin.com" in href:
                continue
            seen.add(key)
            out.append(_posting(key, text, key))
    return out


def collect(row):
    kind, ref = row.get("jobs_source", ""), row.get("jobs_source_ref", "")
    if not kind or kind == "none":
        return None
    try:
        if kind == "careers_page":
            postings = careers_page_postings(ref)
        else:
            postings = fetch_ats(kind, ref)
            if postings is None:
                return {"source": kind, "ref": ref, "error": "job board did not answer", "postings": []}
        return {"source": kind, "ref": ref, "postings": postings}
    except Exception as e:
        return {"source": kind, "ref": ref, "error": f"{type(e).__name__}: {e}"[:200], "postings": []}
