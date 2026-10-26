"""Monthly executive briefing: docs/briefing.html (current) and docs/briefings/YYYY-MM.html (archive).

Everything numeric is computed from the watchlist (market map fields), the latest snapshot and
the movers ranking. The analyst layer (pipeline stage, recommendation, next action, memo notes)
comes from data/pipeline.csv, which is edited by hand. Nothing is estimated: valuations, TAM and
burn are not in the data and are shown as not available.
"""

import csv
import json
import re
from datetime import date

from . import backtest
from .common import DATA, DOCS, ROOT
from .watchlist import TARGET_FUNDS

PIPELINE = DATA / "pipeline.csv"
PIPELINE_STAGES = ["Watch", "Track", "Engage", "Diligence", "Term sheet", "Memo"]

# Thresholds for the raising-window matrix.
RAISE_WINDOW_MONTHS = 15     # most seed and Series A companies raise again 15-24 months after a round
HIRING_MIN_ROLES = 3
GREEK_TICKET_MAX_USD_M = 20  # rounds above this are led by larger, mostly non-Greek funds
MATRIX_MAX_MONTHS = 72
RECENT_MONTHS = 6


def usd_millions(amount):
    """USD figure in millions from the dataset's amount text, or None. Unverified text is skipped."""
    a = (amount or "").strip()
    if not a or re.match(r"(UNVERIFIED|Not |No |Undisclosed|Acquisition)", a, re.I):
        return None
    m = re.search(r"USD\s*([\d.]+)\s*([MK])", a)
    if not m:
        return None
    v = float(m.group(1))
    return v if m.group(2) == "M" else v / 1000


def round_month(text):
    """(year, month) from the dataset's date text when it starts with YYYY-MM, else None."""
    m = re.match(r"\s*(\d{4})-(\d{2})", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def months_between(ym, today):
    return (today.year - ym[0]) * 12 + (today.month - ym[1])


def stage_bucket(stage, usd):
    s = (stage or "").lower()
    if s.startswith("exited"):
        return "Exited"
    if "late stage" in s or "series c" in s or (usd or 0) >= 100:
        return "Late stage"
    if re.search(r"series [ab]|growth|venture debt", s):
        return "Series A / B"
    if "seed" in s:
        return "Pre-seed / seed"
    return "Non-venture"


def read_pipeline():
    if not PIPELINE.exists():
        return []
    with open(PIPELINE, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build(rows, statuses, movers, generated_at, snapshot=None):
    today = date.fromisoformat(generated_at[:10])
    st = {s["company_id"]: s for s in statuses}
    mv = {m["company_id"]: m for m in movers}
    pipe = {p["company_id"]: p for p in read_pipeline()}

    companies = []
    for r in rows:
        usd = usd_millions(r["last_round_amount"])
        ym = round_month(r["last_round_date"])
        s = st[r["company_id"]]
        companies.append({
            "id": r["company_id"], "company": r["company"], "category": r["category"],
            "sub_sector": r["sub_sector"], "what": r["what_they_do"], "map_status": r["map_status"],
            "stage": r["stage"], "bucket": stage_bucket(r["stage"], usd),
            "amount": r["last_round_amount"], "round_date": r["last_round_date"],
            "usd": usd, "months": months_between(ym, today) if ym else None,
            "roles": s["open_roles"], "momentum": mv[r["company_id"]]["momentum"],
            "funds": [f for f in r["greek_funds"].split(" | ") if f], "fund_status": r["greek_fund_status"],
            "investors": r["investors"], "verification": r["verification_status"],
            "greek_link": r["hq_greek_link"],
            "visible": bool(r["github_org"] or (r["jobs_source"] not in ("", "none")) or s["latest_funding"]
                            or s.get("eu_projects")),
        })

    # KPIs.
    recent = [c for c in companies if c["months"] is not None and c["months"] < RECENT_MONTHS
              and c["bucket"] in ("Pre-seed / seed", "Series A / B")]
    recent_usd = [c for c in recent if c["usd"] is not None]
    by_cat = {}
    for c in recent_usd:
        by_cat[c["category"]] = by_cat.get(c["category"], 0) + c["usd"]
    top_cat = max(by_cat.items(), key=lambda kv: kv[1]) if by_cat else None
    target_backed = [c for c in companies if set(c["funds"]) & set(TARGET_FUNDS)]
    kpis = {
        "tracked": len(companies),
        "include": sum(1 for c in companies if c["map_status"] == "Include"),
        "borderline": sum(1 for c in companies if c["map_status"] == "Borderline"),
        "recent_usd": round(sum(c["usd"] for c in recent_usd), 1),
        "recent_rounds": [{"company": c["company"], "usd": c["usd"], "date": c["round_date"][:7]} for c in
                          sorted(recent_usd, key=lambda c: -c["usd"])],
        "recent_other": [{"company": c["company"], "amount": c["amount"]} for c in recent if c["usd"] is None],
        "target_backed": len(target_backed),
        "target_backed_current": sum(1 for c in target_backed if c["fund_status"] == "current"),
        "fund_counts": {f: sum(1 for c in companies if f in c["funds"]) for f in TARGET_FUNDS},
        "top_sector": ({"name": top_cat[0], "usd": round(top_cat[1], 1),
                        "companies": [c["company"] for c in recent_usd if c["category"] == top_cat[0]]}
                       if top_cat else None),
    }

    # EU grants signed in the last 6 months (CORDIS), from the snapshot.
    cutoff = f"{(today.year * 12 + today.month - 1 - RECENT_MONTHS) // 12:04d}-" \
             f"{(today.year * 12 + today.month - 1 - RECENT_MONTHS) % 12 + 1:02d}"
    names = {r["company_id"]: r["company"] for r in rows}
    eu_recent = []
    for cid, c in ((snapshot or {}).get("companies") or {}).items():
        for g in (c.get("grants") or {}).get("items", []):
            if g["signed"][:7] >= cutoff:
                eu_recent.append({"company": names.get(cid, cid), "acronym": g["acronym"], "title": g["title"],
                                  "signed": g["signed"][:10], "eur_m": round(g["eu_contribution"] / 1e6, 2),
                                  "url": g["url"]})
    eu_recent.sort(key=lambda g: g["signed"], reverse=True)
    kpis["eu_recent"] = len(eu_recent)
    kpis["eu_recent_companies"] = len({g["company"] for g in eu_recent})

    # Raising-window matrix: venture-stage companies with a dated USD round.
    matrix = [c for c in companies if c["bucket"] in ("Pre-seed / seed", "Series A / B")
              and c["usd"] is not None and c["months"] is not None and c["months"] <= MATRIX_MAX_MONTHS]
    prime = [c for c in matrix if c["months"] >= RAISE_WINDOW_MONTHS and (c["roles"] or 0) >= HIRING_MIN_ROLES]
    candidates = [c for c in prime if c["usd"] <= GREEK_TICKET_MAX_USD_M]

    # Funnel.
    stage_of = {cid: p["pipeline_stage"] for cid, p in pipe.items()}
    later = lambda s: PIPELINE_STAGES.index(s) if s in PIPELINE_STAGES else 0
    funnel = [
        ["Watch", len(companies), "companies on the watchlist"],
        ["Moving", sum(1 for m in movers if m["momentum"] > 0), "scored by the weekly signals"],
        ["Engage candidates", len(candidates), "raising window + hiring, Greek-fund ticket size"],
        ["Engaged", sum(1 for s in stage_of.values() if later(s) >= later("Engage") and s != "Memo"),
         "founders contacted"],
        ["Diligence / term sheet", sum(1 for s in stage_of.values() if s in ("Diligence", "Term sheet")), ""],
        ["Memo", sum(1 for s in stage_of.values() if s == "Memo"), "memos written"],
    ]

    # Sector by stage.
    buckets = ["Pre-seed / seed", "Series A / B", "Late stage", "Exited", "Non-venture"]
    cats = sorted({c["category"] for c in companies}, key=lambda k: -sum(1 for c in companies if c["category"] == k))
    sector_stage = {"categories": cats, "buckets": buckets,
                    "counts": [[sum(1 for c in companies if c["category"] == k and c["bucket"] == b) for k in cats]
                               for b in buckets]}

    # Signal coverage by sector: where the weekly signals can and cannot see.
    coverage = []
    for k in cats:
        rs = [r for r in rows if r["category"] == k]
        coverage.append({"category": k, "n": len(rs),
                         "github": sum(1 for r in rs if r["github_org"] and r["github_org"] != "none"),
                         "grants": sum(1 for r in rs if st[r["company_id"]].get("eu_projects")),
                         "jobs": sum(1 for r in rs if r["jobs_source"] not in ("", "none"))})

    # Pipeline table: hand-kept rows, plus data-suggested candidates not yet in the file.
    cmap = {c["id"]: c for c in companies}
    pipeline = []
    for cid, p in pipe.items():
        c = cmap.get(cid)
        if c:
            pipeline.append({**_brief(c), **{k: p.get(k, "") for k in (
                "pipeline_stage", "recommendation", "next_action", "owner", "risk_notes",
                "memo_market", "memo_edge", "memo_risks", "memo_terms", "updated")}, "suggested": False})
    for c in candidates:
        if c["id"] not in pipe:
            pipeline.append({**_brief(c), "pipeline_stage": "Watch", "recommendation": "Review",
                             "next_action": "Add to data/pipeline.csv with a view", "owner": "",
                             "risk_notes": "", "suggested": True})
    order = {s: i for i, s in enumerate(PIPELINE_STAGES)}
    cand_ids = {c["id"] for c in candidates}
    pipeline.sort(key=lambda p: (p["id"] not in cand_ids, -order.get(p["pipeline_stage"], 0), p["company"]))

    # Red flags, from the data.
    flags = []
    for p in pipeline:
        v = p["verification"]
        if re.search(r"UNVERIFIED|conflict|disputed|profile pages only|not sourced", v + " " + p["amount"] + " " + p["stage"], re.I):
            flags.append({"company": p["company"], "flag": v or "Round data unconfirmed"})
    invisible = [c["company"] for c in companies if not c["visible"] and c["bucket"] != "Exited"]

    # Gaps.
    gaps = {
        "thin_categories": [(k, n) for k in cats if (n := sum(1 for c in companies if c["category"] == k)) <= 2],
        "funds_without_companies": [f for f, n in kpis["fund_counts"].items() if n == 0],
        "invisible": invisible,
        "large_rounds": [c["company"] for c in prime if c["usd"] > GREEK_TICKET_MAX_USD_M],
    }

    return {
        "generated_at": generated_at, "month": generated_at[:7],
        "kpis": kpis, "funnel": funnel, "sector_stage": sector_stage, "coverage": coverage,
        "eu_recent": eu_recent, "backtest": backtest.read(), "draft_post": draft_post(kpis, movers, candidates, eu_recent),
        "matrix": [{"n": c["company"], "x": c["months"], "roles": c["roles"], "usd": c["usd"],
                    "prime": c in prime} for c in matrix],
        "matrix_rules": {"window": RAISE_WINDOW_MONTHS, "roles": HIRING_MIN_ROLES,
                         "ticket": GREEK_TICKET_MAX_USD_M, "max_months": MATRIX_MAX_MONTHS,
                         "left_out": [c["company"] for c in companies if c["bucket"] in ("Pre-seed / seed", "Series A / B")
                                      and c not in matrix]},
        "candidates": [c["company"] for c in candidates],
        "pipeline": pipeline, "flags": flags, "gaps": gaps,
    }


def draft_post(kpis, movers, candidates, eu_recent):
    """A plain-text monthly post built only from figures on the page. Edit before posting."""
    lines = [f"Greek deep tech this month: what moved across the {kpis['tracked']} companies I track.", ""]
    if kpis["recent_rounds"]:
        top = ", ".join(f"{r['company']} (${r['usd']}M)" for r in kpis["recent_rounds"][:3])
        lines.append(f"- ${kpis['recent_usd']}M disclosed in early-stage rounds over the last 6 months. Largest: {top}.")
    if kpis["top_sector"]:
        lines.append(f"- {kpis['top_sector']['name']} led recent capital with ${kpis['top_sector']['usd']}M.")
    if eu_recent:
        lines.append(f"- {len(eu_recent)} EU-funded projects signed in the last 6 months by "
                     f"{len({g['company'] for g in eu_recent})} companies, most recently "
                     f"{', '.join(dict.fromkeys(g['company'] for g in eu_recent[:3]))}.")
    moving = [m for m in movers if m["momentum"] > 0][:3]
    if moving:
        lines.append(f"- Most active on public signals: {', '.join(m['company'] for m in moving)}.")
    if candidates:
        lines.append(f"- In their usual raising window and hiring: {', '.join(c['company'] for c in candidates)}.")
    lines += ["", "Sources, method and the live tracker: https://geve-ops.github.io/vc-dealflow-tracker/briefing.html"]
    return "\n".join(lines)


def _brief(c):
    return {"id": c["id"], "company": c["company"], "category": c["category"], "sub_sector": c["sub_sector"],
            "what": c["what"], "amount": c["amount"], "round_date": c["round_date"], "stage": c["stage"],
            "months": c["months"], "roles": c["roles"], "momentum": c["momentum"], "funds": c["funds"],
            "investors": c["investors"], "verification": c["verification"], "greek_link": c["greek_link"]}


def write(payload):
    """Write the current briefing and this month's archive copy (later runs in the month replace it)."""
    archive = DOCS / "briefings"
    archive.mkdir(parents=True, exist_ok=True)
    payload["archive"] = sorted({p.stem for p in archive.glob("*.html")} | {payload["month"]}, reverse=True)
    template = (ROOT / "tracker" / "briefing_template.html").read_text(encoding="utf-8")
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = template.replace("/*__DATA__*/null", data)
    (DOCS / "briefing.html").write_text(html, encoding="utf-8")
    # The archive copy sits one folder down, so its page links are adjusted.
    (archive / f"{payload['month']}.html").write_text(
        html.replace('const BASE = "";', 'const BASE = "../";'), encoding="utf-8")
    return DOCS / "briefing.html"
