"""Tests for the two scoring rules that were overcounting.

    python -m unittest discover tests
"""

import json
import unittest
from pathlib import Path

from tracker import backtest, score  # noqa: F401  backtest first, as in run.py (briefing and backtest import each other)
from tracker.digest import company_changes
from tracker.signals_jobs import merge_by_id
from tracker.signals_news import headline_kind

SNAPSHOTS = Path(__file__).resolve().parent.parent / "data" / "snapshots"

# Headlines that earned funding points between 2026-10-26 and 2026-11-16 but announce no round.
NOT_FUNDING = [
    "Study Finds Hack The Box Cybersecurity Platform Delivered 330% Return on Investment",
    "European Space Giant Open Cosmos Eyes Major India Investment After PM Modi Meet",
    "European space company Open Cosmos signals India investment interest after CEO meets PM Modi",
    "Momentus Secures Contract to Host OQ Technology 5G Payload on Vigoride-9 Mission",
    "Momentus Inc. Secures Contract To Host OQ Technology 5G Payload On Vigoride-9 Mission",
    # Amount present, but not a round.
    "Indonesias Batang SEZ explores up to $56M tech deal with Axelera AI",
    "UK Government Commercial Agency Selects Open Cosmos for £8 Billion Defense Communications Framework",
    "OQ Technology Secures Australian Smart Forest Monitoring Project Using Satellite IoT",
]

# Real round headlines taken from the saved snapshots.
FUNDING = [
    "Proxy Foods raises $6M seed round",
    "Anodyne Nanotech Closed a $12.6 Million Series A to Advance Once-Weekly GLP-1 Patch into Phase I Clinical Trials",
    "Perceptual Robotics Secures Over £4 Million to Scale AI Wind Turbine Inspections",
    "Open Cosmos secures €300M to expand satellite intelligence and connectivity",
    "Pallma AI closes $1.6M pre-seed round for AI agent security",
    "Anacalypsis Therapeutics: Pre-seed χρηματοδότηση από την Metavallon VC",
    "Η εταιρεία δορυφόρων Open Cosmos άντλησε 300 εκατ. ευρώ",
    "Open Cosmos: Εξασφάλιση χρηματοδότησης ύψους 300 εκατ. ευρώ για να αυξήσει την παραγωγή δορυφόρων",
]


class FundingHeadlineTest(unittest.TestCase):
    def test_not_funding(self):
        for h in NOT_FUNDING:
            with self.subTest(h=h):
                self.assertEqual(headline_kind(h), "press")

    def test_funding(self):
        for h in FUNDING:
            with self.subTest(h=h):
                self.assertEqual(headline_kind(h), "funding")


class MultiLocationJobTest(unittest.TestCase):
    def test_merge_by_id(self):
        posts = [{"id": "A", "title": "Engineer", "url": "u", "published": "", "location": "Athens, Greece"},
                 {"id": "A", "title": "Engineer", "url": "u", "published": "", "location": "London, United Kingdom"},
                 {"id": "A", "title": "Engineer", "url": "u", "published": "", "location": "Athens, Greece"},
                 {"id": "B", "title": "Designer", "url": "v", "published": "", "location": ""}]
        merged = merge_by_id(posts)
        self.assertEqual([j["id"] for j in merged], ["A", "B"])
        self.assertEqual(merged[0]["location"], "Athens, Greece; London, United Kingdom")

    def test_hack_the_box_week_of_2026_11_16(self):
        # Workable lists FBD643CA7D six times; the week has three new postings.
        cur = json.loads((SNAPSHOTS / "2026-11-16.json").read_text(encoding="utf-8"))
        prev = json.loads((SNAPSHOTS / "2026-11-09.json").read_text(encoding="utf-8"))
        row = {"company_id": "GRDT-031", "company": "Hack The Box", "category": "Space & Defense"}
        changes = company_changes(row, cur, prev, cur["window_start"])
        new_roles = [c for c in changes if c["kind"] == "new_role"]
        self.assertEqual(len(new_roles), 3)
        self.assertEqual(score.week_scores(changes, [row])["GRDT-031"]["hiring"], 3)


if __name__ == "__main__":
    unittest.main()
