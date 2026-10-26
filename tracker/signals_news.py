"""Funding news via Google News RSS search (no key needed), in English and Greek.

A headline is kept only if it contains one of the company's news_terms (exact phrase,
case-insensitive). It is tagged "funding" when the headline itself uses funding language;
other matches are kept as "press" because the search query asked for funding terms in the body.
"""

import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime

from .common import http_get

FEEDS = [
    ("en", "hl=en-US&gl=US&ceid=US:en",
     '(funding OR raises OR raised OR investment OR investors OR "seed round" OR "series A" OR "series B" '
     'OR "pre-seed" OR acquires OR acquired OR acquisition OR grant)'),
    ("el", "hl=el&gl=GR&ceid=GR:el",
     "(χρηματοδότηση OR επένδυση OR αντλεί OR άντλησε OR εξαγορά OR γύρο)"),
]
WINDOW = "when:90d"

FUNDING_RE = re.compile(
    r"\b(rais(e|es|ed|ing)|funding|funded|invest(s|ed|ment|or|ors)?|seed|pre-seed|series [a-e]|round|"
    r"backs|backed|secures?|secured|closes?|grant|acquir(e|es|ed|ing)|acquisition|valuation|ipo|"
    r"χρηματοδότηση|επένδυση|αντλεί|άντλησε|εξαγορ\w*|γύρο\w*)\b", re.I)


def _terms(row):
    return [t.strip() for t in row.get("news_terms", "").split("|") if t.strip()]


def _term_in(title, terms):
    low = title.lower()
    for t in terms:
        if re.search(r"(?<![\w])" + re.escape(t.lower()) + r"(?![\w])", low):
            return True
    return False


def collect(row):
    terms = _terms(row)
    if not terms:
        return None
    name_q = " OR ".join(f'"{t}"' for t in terms)
    items, errors, seen = [], [], set()
    for lang, locale, funding_q in FEEDS:
        q = f"({name_q}) {funding_q} {WINDOW}"
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&{locale}"
        try:
            st, _, xml = http_get(url)
            if st != 200:
                errors.append(f"{lang}: HTTP {st}")
                continue
            root = ET.fromstring(xml.encode("utf-8"))
        except Exception as e:
            errors.append(f"{lang}: {type(e).__name__}")
            continue
        for it in root.iter("item"):
            title = it.findtext("title") or ""
            src_el = it.find("source")
            source = src_el.text if src_el is not None else ""
            headline = title[: -len(f" - {source}")] if source and title.endswith(f" - {source}") else title
            if not _term_in(headline, terms):
                continue
            guid = it.findtext("guid") or it.findtext("link")
            if guid in seen:
                continue
            seen.add(guid)
            try:
                published = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                published = ""
            items.append({
                "id": guid,
                "title": headline.strip(),
                "url": it.findtext("link"),
                "source": source,
                "source_url": src_el.get("url", "") if src_el is not None else "",
                "published": published,
                "lang": lang,
                "kind": "funding" if FUNDING_RE.search(headline) else "press",
            })
    items.sort(key=lambda x: x["published"], reverse=True)
    out = {"terms": terms, "items": items}
    if errors:
        out["error"] = "; ".join(errors)
    return out
