"""
NHL Official API Loader v2 - Bronze Layer
==========================================
Source: api-web.nhle.com  (no API key required)

Loads three tables (1 table per endpoint):
  bronze_nhl_score    - /v1/score/{date}              (one row per date)
  bronze_nhl_landing  - /v1/gamecenter/{id}/landing   (one row per game)
  bronze_nhl_boxscore - /v1/gamecenter/{id}/boxscore  (one row per game)

Raw API responses stored as native Oracle JSON (OSON). No parsed columns.

Usage:
  python etl/load_nhl_v2.py --date 2026-02-17
  python etl/load_nhl_v2.py --season 20252026
  python etl/load_nhl_v2.py --backfill-seasons
"""

import sys, os, time, argparse
from datetime import date, timedelta, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import oracledb
from config.db_connect import get_connection

BASE     = "https://api-web.nhle.com"
LOG_PFX  = "[NHLv2]"
DELAY    = 0.2   # seconds between per-game API calls

AVAILABLE_SEASONS = [
    20202021, 20212022, 20222023,
    20232024, 20242025, 20252026,
]


# ── API helpers ───────────────────────────────────────────────

def fetch_score(game_date: str) -> dict:
    r = requests.get(f"{BASE}/v1/score/{game_date}", timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_landing(game_id: int) -> dict:
    r = requests.get(f"{BASE}/v1/gamecenter/{game_id}/landing", timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_boxscore(game_id: int) -> dict:
    r = requests.get(f"{BASE}/v1/gamecenter/{game_id}/boxscore", timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_season_dates(season: int) -> list:
    """Return all game dates in a season from the BUF team schedule."""
    r = requests.get(f"{BASE}/v1/club-schedule-season/BUF/{season}", timeout=15)
    r.raise_for_status()
    data = r.json()
    dates = sorted({
        g["gameDate"]
        for g in data.get("games", [])
        if g.get("gameType") == 2 and g.get("gameState") in ("OFF", "FINAL")
    })
    return dates


def _to_date(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()


# ── Oracle helpers ────────────────────────────────────────────

def score_loaded(cur, game_date) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM bronze_nhl_score WHERE game_date = :1",
        (game_date,)
    )
    return cur.fetchone()[0] > 0


def landing_loaded(cur, game_id: int) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM bronze_nhl_landing WHERE game_id = :1",
        (game_id,)
    )
    return cur.fetchone()[0] > 0


def boxscore_loaded(cur, game_id: int) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM bronze_nhl_boxscore WHERE game_id = :1",
        (game_id,)
    )
    return cur.fetchone()[0] > 0


def insert_score(cur, conn, game_date, data: dict):
    cur.setinputsizes(None, oracledb.DB_TYPE_JSON)
    cur.execute(
        "INSERT INTO bronze_nhl_score (game_date, raw_response) VALUES (:1, :2)",
        (game_date, data)
    )
    conn.commit()


def insert_landing(cur, conn, game_id: int, game_date, data: dict):
    cur.setinputsizes(None, None, oracledb.DB_TYPE_JSON)
    cur.execute(
        "INSERT INTO bronze_nhl_landing (game_id, game_date, raw_response) VALUES (:1, :2, :3)",
        (game_id, game_date, data)
    )
    conn.commit()


def insert_boxscore(cur, conn, game_id: int, game_date, data: dict):
    cur.setinputsizes(None, None, oracledb.DB_TYPE_JSON)
    cur.execute(
        "INSERT INTO bronze_nhl_boxscore (game_id, game_date, raw_response) VALUES (:1, :2, :3)",
        (game_id, game_date, data)
    )
    conn.commit()


def log_result(cur, conn, source, game_date, fetched, inserted, status, msg=None):
    d = _to_date(game_date) if isinstance(game_date, str) else game_date
    cur.callproc("bronze_log", [source, d, fetched, inserted, status, msg or ""])
    conn.commit()


# ── Core loaders ──────────────────────────────────────────────

def load_date(game_date_str: str, conn, load_details=True) -> dict:
    """Load score summary + game details for one calendar date."""
    result = {"dates": 0, "games": 0, "details": 0, "errors": 0}
    cur    = conn.cursor()
    d      = _to_date(game_date_str)

    try:
        if score_loaded(cur, d):
            print(f"{LOG_PFX} {game_date_str}: score already loaded, skipping")
        else:
            data  = fetch_score(game_date_str)
            games = data.get("games", [])
            # Only store if there are finished regular-season games
            finished = [g for g in games
                        if g.get("gameType") == 2
                        and g.get("gameState") in ("OFF", "FINAL")]
            if finished:
                insert_score(cur, conn, d, data)
                log_result(cur, conn, "NHL_SCORE", d, len(games), 1, "SUCCESS")
                result["dates"] += 1
                result["games"] += len(finished)
                print(f"{LOG_PFX} {game_date_str}: loaded {len(finished)} games")
            else:
                print(f"{LOG_PFX} {game_date_str}: no finished regular-season games")

        if load_details:
            # Discover game IDs from the score response (or re-fetch if skipped)
            data  = fetch_score(game_date_str)
            games = [g for g in data.get("games", [])
                     if g.get("gameType") == 2
                     and g.get("gameState") in ("OFF", "FINAL")]

            detail_count = 0
            for g in games:
                gid = g["id"]
                time.sleep(DELAY)
                try:
                    # Landing
                    if not landing_loaded(cur, gid):
                        landing = fetch_landing(gid)
                        gdate   = _to_date(landing.get("gameDate", game_date_str))
                        insert_landing(cur, conn, gid, gdate, landing)

                    # Boxscore
                    if not boxscore_loaded(cur, gid):
                        boxscore = fetch_boxscore(gid)
                        gdate    = _to_date(game_date_str)
                        insert_boxscore(cur, conn, gid, gdate, boxscore)

                    detail_count += 1
                except Exception as e:
                    result["errors"] += 1
                    print(f"{LOG_PFX} {game_date_str} game {gid}: ERROR - {e}")
                    log_result(cur, conn, "NHL_LANDING", d, 0, 0, "ERROR", str(e)[:4000])

            if detail_count:
                result["details"] += detail_count
                print(f"{LOG_PFX} {game_date_str}: {detail_count} game details loaded")

    except Exception as e:
        result["errors"] += 1
        print(f"{LOG_PFX} {game_date_str}: ERROR - {e}")
    finally:
        cur.close()

    return result


def load_season(season: int, conn) -> dict:
    """Load all finished regular-season games for a given season."""
    result = {"dates": 0, "games": 0, "details": 0, "errors": 0}
    print(f"{LOG_PFX} Loading season {season}...")

    try:
        dates = fetch_season_dates(season)
        print(f"{LOG_PFX}   Found {len(dates)} game dates with finished regular-season games")
    except Exception as e:
        print(f"{LOG_PFX} Season {season}: ERROR fetching schedule - {e}")
        result["errors"] += 1
        return result

    for d in dates:
        t = load_date(d, conn, load_details=True)
        for k in result:
            result[k] += t[k]

    return result


# ── Entry point ───────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NHL Bronze v2 Loader")
    group  = parser.add_mutually_exclusive_group()
    group.add_argument("--date",             help="Single date YYYY-MM-DD")
    group.add_argument("--season",           type=int, help="Season e.g. 20252026")
    group.add_argument("--backfill-seasons", action="store_true",
                       help="Load all 6 available seasons")
    parser.add_argument("--no-details", action="store_true",
                        help="Skip per-game landing/boxscore calls")
    args = parser.parse_args()

    print("=" * 60)
    print("NHL BRONZE v2 LOADER")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60)

    conn   = get_connection("bronze_2")
    totals = {"dates": 0, "games": 0, "details": 0, "errors": 0}

    if args.backfill_seasons:
        for season in AVAILABLE_SEASONS:
            t = load_season(season, conn)
            for k in totals: totals[k] += t[k]
    elif args.season:
        totals = load_season(args.season, conn)
    elif args.date:
        totals = load_date(args.date, conn, load_details=not args.no_details)
    else:
        today = str(date.today())
        totals = load_date(today, conn, load_details=not args.no_details)

    conn.close()
    print(f"\nTotals: {totals}")
    print(f"Finished: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
