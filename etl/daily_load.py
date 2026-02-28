"""
Daily Orchestrator - Bronze Layer
===================================
Runs all three source loaders in sequence for the current day.
Designed to be scheduled once per day (e.g. 2am via cron).

Usage:
  python etl/daily_load.py                  # today's data, all 3 sources
  python etl/daily_load.py --backfill       # historical load for all sources
  python etl/daily_load.py --source nhl     # only NHL
  python etl/daily_load.py --source espn    # only ESPN
  python etl/daily_load.py --source sportdb # only SportDB

Cron example (daily at 2am):
  0 2 * * * /path/to/python /path/to/etl/daily_load.py >> /path/to/data/daily_load.log 2>&1
"""

import sys, os, argparse
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.db_connect import get_connection

# Import individual loaders
from etl.load_nhl     import load_date as nhl_load_date,     load_season as nhl_load_season,    AVAILABLE_SEASONS
from etl.load_espn    import load_date as espn_load_date,    load_range  as espn_load_range,    SEASON_DATE_RANGES
from etl.load_sportdb import load_offset as sportdb_load_offset


def run_daily(conn, sources: list):
    """Load today's data from the specified sources."""
    today    = date.today()
    today_str = str(today)
    results  = {}

    if "nhl" in sources:
        print("\n── NHL Official API ─────────────────────────────")
        results["nhl"] = nhl_load_date(today_str, conn, load_details=True)

    if "espn" in sources:
        print("\n── ESPN NHL ─────────────────────────────────────")
        results["espn"] = espn_load_date(today, conn)

    if "sportdb" in sources:
        print("\n── SportDB Flashscore (offset=0, today) ─────────")
        results["sportdb"] = sportdb_load_offset(0, conn)

    return results


def run_backfill(conn, sources: list):
    """Historical bulk load for all sources."""
    results = {}

    if "nhl" in sources:
        print("\n── NHL Official API - All 6 Seasons ────────────")
        nhl_totals = {"dates": 0, "games": 0, "details": 0, "errors": 0}
        for season in AVAILABLE_SEASONS:
            t = nhl_load_season(season, conn)
            for k in nhl_totals: nhl_totals[k] += t[k]
        results["nhl"] = nhl_totals
        print(f"NHL backfill totals: {nhl_totals}")

    if "espn" in sources:
        print("\n── ESPN NHL - All Seasons ───────────────────────")
        espn_totals = {"loaded": 0, "skipped": 0, "empty": 0, "errors": 0, "games": 0}
        for season, (start, end) in SEASON_DATE_RANGES.items():
            print(f"  ESPN season {season}...")
            t = espn_load_range(start, min(end, str(date.today())), conn)
            for k in espn_totals: espn_totals[k] += t[k]
        results["espn"] = espn_totals
        print(f"ESPN backfill totals: {espn_totals}")

    if "sportdb" in sources:
        print("\n── SportDB - Last 7 Days ────────────────────────")
        sdb_results = [sportdb_load_offset(o, conn) for o in range(-7, 1)]
        results["sportdb"] = {
            "loaded":  sum(1 for r in sdb_results if r["status"] == "SUCCESS"),
            "games":   sum(r["games"] for r in sdb_results),
        }
        print(f"SportDB backfill totals: {results['sportdb']}")

    return results


def print_summary(results: dict, mode: str):
    print("\n" + "=" * 60)
    print(f"LOAD SUMMARY ({mode.upper()})")
    print("=" * 60)
    for source, r in results.items():
        print(f"  {source.upper():10s}: {r}")


def main():
    parser = argparse.ArgumentParser(description="Daily Bronze Layer Orchestrator")
    parser.add_argument("--backfill", action="store_true",
                        help="Run full historical load instead of today only")
    parser.add_argument("--source",   choices=["nhl","espn","sportdb"],
                        help="Run only one source (default: all three)")
    args = parser.parse_args()

    sources = [args.source] if args.source else ["nhl", "espn", "sportdb"]

    print("=" * 60)
    print("BRONZE LAYER DAILY ORCHESTRATOR")
    print(f"Sources: {', '.join(s.upper() for s in sources)}")
    print(f"Mode   : {'BACKFILL' if args.backfill else 'DAILY'}")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60)

    conn = get_connection("bronze")

    try:
        if args.backfill:
            results = run_backfill(conn, sources)
            print_summary(results, "backfill")
        else:
            results = run_daily(conn, sources)
            print_summary(results, "daily")
    finally:
        conn.close()

    print(f"\nFinished: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
