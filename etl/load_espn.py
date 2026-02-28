"""
ESPN NHL Scoreboard Loader - Bronze Layer
==========================================
Source: site.api.espn.com  (no API key required)

Loads: bronze_espn_daily  (one row per calendar date)

ESPN adds: game headlines, venue/attendance, detailed game status (Final/OT, etc.),
           Stars of Game with player stats — complements the NHL API data.

Usage:
  python etl/load_espn.py --date 2026-02-17         # one date
  python etl/load_espn.py --date-range 2026-01-01 2026-02-17
  python etl/load_espn.py --season 2025             # full season year (Oct-Apr)
  python etl/load_espn.py --backfill                # 2023-present
"""

import sys, os, argparse
from datetime import date, timedelta, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import oracledb
from config.db_connect import get_connection

BASE    = "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard"
HEADERS = {"User-Agent": "NHL-Analytics-BU779/1.0"}
LOG_PFX = "[ESPN]"

# Season ranges: NHL season runs roughly Oct–Apr
SEASON_DATE_RANGES = {
    2022: ("2022-10-01", "2023-04-30"),
    2023: ("2023-10-01", "2024-04-30"),
    2024: ("2024-10-01", "2025-04-30"),
    2025: ("2025-10-01", "2026-04-30"),
}


# ── API helpers ──────────────────────────────────────────────

def get_scoreboard(game_date: date) -> dict:
    """GET ESPN scoreboard for a single date."""
    date_str = game_date.strftime("%Y%m%d")
    r = requests.get(BASE, headers=HEADERS, params={"dates": date_str}, timeout=15)
    r.raise_for_status()
    return r.json()


def date_range(start: str, end: str):
    """Yield date objects from start to end inclusive (YYYY-MM-DD strings)."""
    d = datetime.strptime(start, "%Y-%m-%d").date()
    e = datetime.strptime(end,   "%Y-%m-%d").date()
    while d <= e:
        yield d
        d += timedelta(days=1)


# ── Oracle helpers ───────────────────────────────────────────

def already_loaded(cur, game_date: date) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM bronze_espn_daily WHERE game_date = :1",
        (game_date,)
    )
    return cur.fetchone()[0] > 0


def insert_espn(cur, conn, game_date: date, data: dict) -> int:
    game_count = len(data.get("events", []))
    cur.execute(
        """INSERT INTO bronze_espn_daily (game_date, game_count, raw_response)
           VALUES (:1, :2, :3)""",
        (game_date, game_count, data)  # native JSON column: pass dict directly (oracledb → OSON)
    )
    conn.commit()
    cur.execute("SELECT load_id FROM bronze_espn_daily WHERE game_date = :1", (game_date,))
    return cur.fetchone()[0]


def log_result(cur, conn, game_date, fetched, inserted, status, msg=None):
    cur.callproc("bronze_log", ["ESPN", game_date, fetched, inserted, status, msg or ""])
    conn.commit()


# ── Core loader ──────────────────────────────────────────────

def load_date(game_date: date, conn) -> dict:
    result = {"date": str(game_date), "status": "PENDING", "games": 0}
    cur    = conn.cursor()

    try:
        if already_loaded(cur, game_date):
            result["status"] = "SKIPPED"
            return result

        data   = get_scoreboard(game_date)
        events = data.get("events", [])

        if not events:
            result["status"] = "EMPTY"
            log_result(cur, conn, game_date, 0, 0, "EMPTY")
            return result

        insert_espn(cur, conn, game_date, data)
        result.update({"status": "SUCCESS", "games": len(events)})
        log_result(cur, conn, game_date, len(events), len(events), "SUCCESS")
        print(f"{LOG_PFX} {game_date}: {len(events)} games loaded")

    except Exception as e:
        result["status"] = "ERROR"
        print(f"{LOG_PFX} {game_date}: ERROR - {e}")
        try:
            log_result(cur, conn, game_date, 0, 0, "ERROR", str(e)[:4000])
        except Exception:
            pass
    finally:
        cur.close()

    return result


def load_range(start: str, end: str, conn) -> dict:
    totals = {"loaded": 0, "skipped": 0, "empty": 0, "errors": 0, "games": 0}
    for d in date_range(start, end):
        r = load_date(d, conn)
        s = r["status"]
        if s == "SUCCESS":
            totals["loaded"] += 1
            totals["games"]  += r["games"]
        elif s == "SKIPPED": totals["skipped"] += 1
        elif s == "EMPTY":   totals["empty"]   += 1
        elif s == "ERROR":   totals["errors"]  += 1
    return totals


# ── Entry point ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ESPN NHL Bronze Loader")
    group  = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--date",        help="Single date YYYY-MM-DD")
    group.add_argument("--date-range",  nargs=2, metavar=("START","END"),
                       help="Date range YYYY-MM-DD YYYY-MM-DD")
    group.add_argument("--season",      type=int,
                       help="Season start year e.g. 2025 for 2025-26")
    group.add_argument("--backfill",    action="store_true",
                       help="Load all seasons from 2022-present")
    args = parser.parse_args()

    print("=" * 60)
    print("ESPN NHL BRONZE LOADER")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60)

    conn = get_connection("bronze")

    if args.date:
        d = datetime.strptime(args.date, "%Y-%m-%d").date()
        r = load_date(d, conn)
        print(f"\nDone: {r}")

    elif args.date_range:
        t = load_range(args.date_range[0], args.date_range[1], conn)
        print(f"\nDone: {t}")

    elif args.season:
        if args.season not in SEASON_DATE_RANGES:
            print(f"Unknown season {args.season}. Available: {list(SEASON_DATE_RANGES)}")
            sys.exit(1)
        start, end = SEASON_DATE_RANGES[args.season]
        t = load_range(start, min(end, date.today().strftime("%Y-%m-%d")), conn)
        print(f"\nSeason {args.season}: {t}")

    elif args.backfill:
        grand = {"loaded": 0, "skipped": 0, "empty": 0, "errors": 0, "games": 0}
        for season, (start, end) in SEASON_DATE_RANGES.items():
            print(f"\nLoading season {season}...")
            t = load_range(start, min(end, date.today().strftime("%Y-%m-%d")), conn)
            print(f"  Season {season}: {t}")
            for k in grand: grand[k] += t[k]
        print(f"\nAll seasons: {grand}")

    conn.close()
    print(f"\nFinished: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
