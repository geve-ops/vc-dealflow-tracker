"""Build data/watchlist.csv from the market map dataset (rows with map_status Include or Borderline).

Re-running keeps the enrichment columns already filled in watchlist.csv, so it is safe to
run again after the market map gains companies.
"""

import csv
import re

from .common import WATCHLIST, WATCHLIST_FIELDS, clean_url, write_watchlist

# Exact phrases a news headline must contain to count as being about the company.
# Default is the company name without anything in brackets. Overrides cover renames
# and names that are common words or shared with other firms.
NEWS_TERMS = {
    "GRDT-006": "Augmenta",
    "GRDT-012": "Moveo.AI | Moveo AI",
    "GRDT-016": "TileDB | Tile.ai",
    "GRDT-017": "Proxy Foods",
    "GRDT-024": "Intelligencia AI | Intelligencia.ai",
    "GRDT-026": "Anodyne Nanotech | Hero Patch",
    "GRDT-030": "Delian Alliance | Delian Industries",
    "GRDT-034": "Open Cosmos",
    "GRDT-037": "DeepSea Technologies",
    "GRDT-043": "Achira",
    "GRDT-045": "Circuits Integrated Hellas",
    "GRDT-051": "Core Innovation and Technology | Core Innovation",
    "GRDT-056": "Pallma AI | Verno Labs",
    "GRDT-059": "Purposeful health | Purposeful.eu",
    "GRDT-063": "Navenio",
    "GRDT-064": "Terra Robotics",
    "GRDT-068": "Mind The Hack",
    "GRDT-069": "Hoplon AI | Hoplon",
    "GRDT-072": "Seervision",
}


def default_terms(name):
    return re.sub(r"\s*\(.*?\)", "", name).strip()


def build(source_csv):
    existing = {}
    if WATCHLIST.exists():
        with open(WATCHLIST, encoding="utf-8", newline="") as f:
            existing = {r["company_id"]: r for r in csv.DictReader(f)}

    with open(source_csv, encoding="utf-8-sig", newline="") as f:
        src = [r for r in csv.DictReader(f) if r["map_status"] in ("Include", "Borderline")]

    rows = []
    for r in src:
        cid = r["company_id"]
        row = {k: "" for k in WATCHLIST_FIELDS}
        row.update(existing.get(cid, {}))
        row.update({
            "company_id": cid,
            "company": r["company"],
            "category": r["category"],
            "map_status": r["map_status"],
            "website": clean_url(r["website"]),
        })
        # Values typed into the market map win over empty enrichment.
        for col in ("github_org", "linkedin_url"):
            if r.get(col) and not row[col]:
                row[col] = r[col]
                row[col.replace("_org", "_source").replace("_url", "_source")] = "market map dataset"
        if not row["news_terms"]:
            row["news_terms"] = NEWS_TERMS.get(cid, default_terms(r["company"]))
        rows.append(row)

    write_watchlist(rows)
    print(f"watchlist: {len(rows)} companies written to {WATCHLIST}")
    return rows
