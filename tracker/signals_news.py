"""Funding news via Google News RSS search (no key needed), in English and Greek.

A headline is kept only if it contains one of the company's news_terms (exact phrase,
case-insensitive). It is tagged "funding" only when the headline itself names a round
(seed, Series A, raises, funding round...) or an amount (a currency and a figure in thousands,
millions or billions) next to a money word such as funding, secures or investors. Everything
else is "press": "investment" or "secures" alone also appear in ROI studies, contracts and
investment plans.
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

_UNIT = r"(?:k|m|mn|bn|b|thousand|million|billion)\b"
_NUM = r"\d[\d.,]*"
AMOUNT_RE = re.compile(
    rf"(?:[€$£]|\b(?:eur|usd|gbp)\s?){_NUM}\s?{_UNIT}"                     # €4M, $6 million, EUR 1.2m
    rf"|\b{_NUM}\s?{_UNIT}\s?(?:eur|euros?|usd|dollars?|gbp|pounds?)\b"   # 300 million euros
    rf"|{_NUM}\s?(?:εκατ|δισ)",                                           # 300 εκατ., €4 εκατ.
    re.I)
# An amount counts only next to money words, so "$56M tech deal" or "£8 billion framework" do not.
MONEY_RE = re.compile(
    r"\b(?:funding|financing|investments?|investors?|backs|backed|secures?|secured|banks|closes|closed"
    r"|κεφάλαια|χρηματοδότηση\w*|επενδυτ\w*)", re.I)
NOT_A_ROUND_RE = re.compile(r"\b(?:contracts?|deals?|orders?|framework|tenders?|σύμβαση\w*)\b", re.I)
ROUND_RE = re.compile(
    r"\b(?:pre-?\s?seed|seed|series [a-e]|rais(?:e|es|ed|ing)|(?:funding|financing|investment) round"
    r"|αντλεί|άντλησε|αντλούν|γύρο\w* χρηματοδότησης)\b", re.I)


def headline_kind(headline):
    """'funding' if the headline names a round, or an amount together with a money word; else 'press'."""
    if ROUND_RE.search(headline):
        return "funding"
    if AMOUNT_RE.search(headline) and MONEY_RE.search(headline) and not NOT_A_ROUND_RE.search(headline):
        return "funding"
    return "press"


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
                "kind": headline_kind(headline),
            })
    items.sort(key=lambda x: x["published"], reverse=True)
    out = {"terms": terms, "items": items}
    if errors:
        out["error"] = "; ".join(errors)
    return out
