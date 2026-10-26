"""Command line entry point.

    python run.py build-watchlist --source ../greek-deeptech-market-map/data/greek_deeptech_dataset.csv
    python run.py enrich [--force] [--only GRDT-001 GRDT-002]
    python run.py collect [--signals github news jobs]
    python run.py digest
    python run.py weekly          # collect + digest
"""

import argparse
import sys

from tracker import collect, digest, enrich, watchlist


def main(argv=None):
    ap = argparse.ArgumentParser(description="Deal-flow tracker for the Greek Deep Tech Market Map watchlist")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build-watchlist", help="create or refresh data/watchlist.csv from the market map CSV")
    b.add_argument("--source", required=True)
    e = sub.add_parser("enrich", help="fill LinkedIn, GitHub and careers sources from public pages")
    e.add_argument("--force", action="store_true", help="overwrite values already filled")
    e.add_argument("--only", nargs="*", help="company_ids to process")
    c = sub.add_parser("collect", help="run the signals and save a snapshot")
    c.add_argument("--signals", nargs="*", default=["github", "news", "jobs"], choices=["github", "news", "jobs"])
    sub.add_parser("digest", help="write the digest and dashboard from the latest snapshots")
    w = sub.add_parser("weekly", help="collect, then digest")
    w.add_argument("--signals", nargs="*", default=["github", "news", "jobs"], choices=["github", "news", "jobs"])
    a = ap.parse_args(argv)

    if a.cmd == "build-watchlist":
        watchlist.build(a.source)
    elif a.cmd == "enrich":
        enrich.enrich(force=a.force, only=set(a.only) if a.only else None)
    elif a.cmd == "collect":
        collect.collect(signals=tuple(a.signals))
    elif a.cmd == "digest":
        digest.build()
    elif a.cmd == "weekly":
        collect.collect(signals=tuple(a.signals))
        digest.build()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
