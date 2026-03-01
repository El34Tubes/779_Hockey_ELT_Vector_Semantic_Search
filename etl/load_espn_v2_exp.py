"""
ESPN NHL Scoreboard Loader v2 - Bronze Layer
=============================================
Source: site.api.espn.com  (no API key required)

Loads: bronze_espn_scoreboard  (one row per calendar date)

Raw API response stored as native Oracle JSON (OSON). No parsed columns.

Usage:
  python etl/load_espn_v2.py --date 2026-02-17
  python etl/load_espn_v2.py --date-range 2026-01-01 2026-02-17
  python etl/load_espn_v2.py --backfill
"""

import sys, os, argparse
from datetime import date, timedelta, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import oracledb
from config.db_connect import get_connection

BASE    = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard"
LOG_PFX = "[ESPNv2]"

SEASON_DATE_RANGES = {
    2022: ("2022-10-01", "2023-04-30"),
    2023: ("2023-10-01", "2024-04-30"),
    2024: ("2024-10-01", "2025-04-30"),
    2025: ("2025-10-01", "2026-04-30"),
}


# ── API helpers ───────────────────────────────────────────────

def fetch_scoreboard(game_date: date) -> dict:
    r = requests.get(
        BASE,
        params={"dates": game_date.strftime("%Y%m%d"), "limit": 50},
        timeout=15
    )
    r.raise_for_status()
    return r.json()


# ── Oracle helpers ────────────────────────────────────────────

def already_loaded(cur, game_date) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM bronze_espn_scoreboard WHERE game_date = :1",
        (game_date,)
    )
    return cur.fetchone()[0] > 0


def insert_espn(cur, conn, game_date: date, data: dict):
    cur.setinputsizes(None, oracledb.DB_TYPE_JSON)
    cur.execute(
        "INSERT INTO bronze_espn_scoreboard (game_date, raw_response) VALUES (:1, :2)",
        (game_date, data)
    )
    conn.commit()


def log_result(cur, conn, game_date, fetched, inserted, status, msg=None):
    cur.callproc("bronze_log", ["ESPN", game_date, fetched, inserted, status, msg or ""])
    conn.commit()


# ── Core loaders ──────────────────────────────────────────────

def load_date(game_date: date, conn) -> dict:
    result = {"loaded": 0, "skipped": 0, "empty": 0, "errors": 0, "games": 0}
    cur    = conn.cursor()

    try:
        if already_loaded(cur, game_date):
            result["skipped"] = 1
            return result

        data   = fetch_scoreboard(game_date)
        events = data.get("events", [])

        if not events:
            result["empty"] = 1
            log_result(cur, conn, game_date, 0, 0, "EMPTY")
            return result

        insert_espn(cur, conn, game_date, data)
        result.update({"loaded": 1, "games": len(events)})
        log_result(cur, conn, game_date, len(events), 1, "SUCCESS")
        print(f"{LOG_PFX} {game_date}: {len(events)} games loaded")

    except Exception as e:
        result["errors"] = 1
        print(f"{LOG_PFX} {game_date}: ERROR - {e}")
        try:
            log_result(cur, conn, game_date, 0, 0, "ERROR", str(e)[:4000])
        except Exception:
            pass
    finally:
        cur.close()

    return result


def load_range(start: str, end: str, conn) -> dict:
    totals  = {"loaded": 0, "skipped": 0, "empty": 0, "errors": 0, "games": 0}
    current = datetime.strptime(start, "%Y-%m-%d").date()
    end_d   = datetime.strptime(end,   "%Y-%m-%d").date()

    while current <= end_d:
        t = load_date(current, conn)
        for k in totals: totals[k] += t[k]
        current += timedelta(days=1)

    return totals


# ── Entry point ───────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ESPN NHL Bronze v2 Loader")
    group  = parser.add_mutually_exclusive_group()
    group.add_argument("--date",       help="Single date YYYY-MM-DD")
    group.add_argument("--date-range", nargs=2, metavar=("START","END"))
    group.add_argument("--backfill",   action="store_true",
                       help="Load all seasons from SEASON_DATE_RANGES")
    args = parser.parse_args()

    print("=" * 60)
    print("ESPN NHL BRONZE v2 LOADER")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60)

    conn   = get_connection("bronze_2")
    totals = {"loaded": 0, "skipped": 0, "empty": 0, "errors": 0, "games": 0}

    if args.backfill:
        for season, (start, end) in SEASON_DATE_RANGES.items():
            print(f"  ESPN season {season}...")
            t = load_range(start, min(end, str(date.today())), conn)
            for k in totals: totals[k] += t[k]
    elif args.date_range:
        totals = load_range(args.date_range[0], args.date_range[1], conn)
    elif args.date:
        d = datetime.strptime(args.date, "%Y-%m-%d").date()
        totals = load_date(d, conn)
    else:
        totals = load_date(date.today(), conn)

    conn.close()
    print(f"\nTotals: {totals}")
    print(f"Finished: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
