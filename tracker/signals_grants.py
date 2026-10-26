"""EU grants signal from CORDIS, the EU's public database of Horizon Europe and earlier projects.

The CORDIS search answers in JSON without a key. A project counts for a company when one of the
company's news_terms appears in the project's title, summary or participant names. Participant
legal names often differ from brand names, so matching on the text is the reliable route.
Amounts are the EU contribution to the whole project, not only the company's share.
"""

import re
import time
import urllib.parse

from .common import http_json

SEARCH = "https://cordis.europa.eu/search/en"


def _list(x):
    return x if isinstance(x, list) else [x] if x else []


def _mentions(project, terms):
    orgs = _list(((project.get("relations") or {}).get("associations") or {}).get("organization"))
    text = " ".join([project.get("title", ""), project.get("acronym", ""), project.get("teaser", ""),
                     project.get("objective", "")] + [o.get("legalName", "") for o in orgs if isinstance(o, dict)])
    return any(re.search(r"(?<!\w)" + re.escape(t) + r"(?!\w)", text, re.I) for t in terms)


def collect(row):
    terms = [t.strip() for t in row.get("news_terms", "").split("|") if t.strip()]
    if not terms:
        return None
    items, seen = [], set()
    for t in terms:
        q = f"contenttype='project' AND '{t}'"
        st, d = http_json(f"{SEARCH}?q={urllib.parse.quote(q)}&format=json&p=1&num=20")
        if st != 200 or d is None:
            return {"items": items, "error": f"CORDIS HTTP {st}"}
        for hit in _list((d.get("hits") or {}).get("hit")):
            p = hit.get("project") if isinstance(hit, dict) else None
            if not p or p.get("id") in seen or not _mentions(p, terms):
                continue
            seen.add(p["id"])
            items.append({
                "id": p["id"],
                "title": p.get("title", ""),
                "acronym": p.get("acronym", ""),
                "signed": p.get("ecSignatureDate", "") or p.get("startDate", ""),
                "start": p.get("startDate", ""),
                "end": p.get("endDate", ""),
                "eu_contribution": float(p.get("ecMaxContribution") or 0),
                "status": p.get("status", ""),
                "url": f"https://cordis.europa.eu/project/id/{p['id']}",
            })
        time.sleep(0.5)
    items.sort(key=lambda i: i["signed"], reverse=True)
    return {"terms": terms, "items": items}
