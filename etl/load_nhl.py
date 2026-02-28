"""
NHL Official API Loader - Bronze Layer
======================================
Source: api-web.nhle.com  (no API key required)

Loads two tables:
  bronze_nhl_daily       - /v1/score/{date}              (one row per date)
  bronze_nhl_game_detail - /v1/gamecenter/{id}/landing   (one row per game)
                           /v1/gamecenter/{id}/boxscore

Usage:
  python etl/load_nhl.py --date 2026-02-17          # one date
  python etl/load_nhl.py --season 20252026           # full season (daily + details)
  python etl/load_nhl.py --backfill-seasons          # all 6 available seasons
  python etl/load_nhl.py --details-only --date ...   # only fetch game details
"""

import sys, os, time, argparse
from datetime import date, timedelta, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import oracledb
from config.config import Config
from config.db_connect import get_connection

BASE    = "https://api-web.nhle.com"
HEADERS = {"User-Agent": "NHL-Analytics-BU779/1.0"}
LOG_PFX = "[NHL]"

# All seasons available from the API
AVAILABLE_SEASONS = [20202021, 20212022, 20222023, 20232024, 20242025, 20252026]


# ── API helpers ──────────────────────────────────────────────

def get_score(game_date: str) -> dict:
    """GET /v1/score/{date}  returns full day response."""
    r = requests.get(f"{BASE}/v1/score/{game_date}", headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def get_landing(game_id: int) -> dict:
    """GET /v1/gamecenter/{id}/landing"""
    r = requests.get(f"{BASE}/v1/gamecenter/{game_id}/landing", headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def get_boxscore(game_id: int) -> dict:
    """GET /v1/gamecenter/{id}/boxscore"""
    r = requests.get(f"{BASE}/v1/gamecenter/{game_id}/boxscore", headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


def get_season_dates(season: int) -> list[str]:
    """
    Return all dates in a season that have regular-season games.
    Uses one team's full schedule to discover game dates, then deduplicates.
    """
    r = requests.get(f"{BASE}/v1/club-schedule-season/BUF/{season}", headers=HEADERS, timeout=15)
    r.raise_for_status()
    games = r.json().get("games", [])
    # Return unique dates for regular season (gameType=2) finished games
    dates = sorted(set(
        g["gameDate"] for g in games
        if g.get("gameType") == 2 and g.get("gameState") in ("OFF", "FINAL", "F")
    ))
    return dates


# ── Oracle helpers ───────────────────────────────────────────

def _to_date(s: str):
    """Convert YYYY-MM-DD string to Python date for oracledb binding."""
    return datetime.strptime(s, "%Y-%m-%d").date()


def daily_loaded(cur, game_date: str) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM bronze_nhl_daily WHERE game_date = :1",
        (_to_date(game_date),)
    )
    return cur.fetchone()[0] > 0


def detail_loaded(cur, game_id: int) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM bronze_nhl_game_detail WHERE game_id = :1",
        (game_id,)
    )
    return cur.fetchone()[0] > 0


def insert_daily(cur, conn, game_date: str, data: dict) -> int:
    games = data.get("games", [])
    d     = _to_date(game_date)
    cur.execute(
        """INSERT INTO bronze_nhl_daily (game_date, game_count, raw_response)
           VALUES (:1, :2, :3)""",
        (d, len(games), data)  # native JSON column: pass dict directly (oracledb → OSON)
    )
    conn.commit()
    cur.execute("SELECT load_id FROM bronze_nhl_daily WHERE game_date = :1", (d,))
    return cur.fetchone()[0]


def insert_game_detail(cur, conn, game_id: int, landing: dict, boxscore: dict):
    g_date_str = landing.get("gameDate", "")
    g_date     = _to_date(g_date_str) if g_date_str else None
    season     = landing.get("season")
    game_type  = landing.get("gameType")
    home       = landing.get("homeTeam", {}).get("abbrev", "")
    away       = landing.get("awayTeam", {}).get("abbrev", "")
    h_score    = landing.get("homeTeam", {}).get("score")
    a_score    = landing.get("awayTeam", {}).get("score")
    state      = landing.get("gameState", "")

    cur.execute(
        """INSERT INTO bronze_nhl_game_detail
            (game_id, game_date, season, game_type,
             home_team, away_team, home_score, away_score, game_state,
             landing_json, boxscore_json)
           VALUES (:1, :2, :3, :4, :5, :6, :7, :8, :9, :10, :11)""",
        (game_id, g_date, season, game_type,
         home, away, h_score, a_score, state,
         landing, boxscore)  # native JSON columns: pass dicts directly (oracledb → OSON)
    )
    conn.commit()


def log_result(cur, conn, game_date, fetched, inserted, status, msg=None):
    d = _to_date(game_date) if isinstance(game_date, str) else game_date
    cur.callproc("bronze_log", ["NHL_DAILY", d, fetched, inserted, status, msg or ""])
    conn.commit()


# ── Core loaders ─────────────────────────────────────────────

def load_date(game_date: str, conn, load_details: bool = True) -> dict:
    """Load one date: daily summary + optionally all game details."""
    result = {"date": game_date, "daily_status": "PENDING",
              "games_loaded": 0, "details_loaded": 0, "errors": []}
    cur = conn.cursor()

    try:
        # Daily summary
        if daily_loaded(cur, game_date):
            print(f"{LOG_PFX} {game_date}: daily already loaded, skipping")
            result["daily_status"] = "SKIPPED"
        else:
            data  = get_score(game_date)
            games = data.get("games", [])

            if not games:
                print(f"{LOG_PFX} {game_date}: 0 games")
                result["daily_status"] = "EMPTY"
                log_result(cur, conn, game_date, 0, 0, "EMPTY")
            else:
                insert_daily(cur, conn, game_date, data)
                result["daily_status"]  = "SUCCESS"
                result["games_loaded"]  = len(games)
                log_result(cur, conn, game_date, len(games), len(games), "SUCCESS")
                print(f"{LOG_PFX} {game_date}: loaded {len(games)} games")

        # Game details (landing + boxscore per game)
        if load_details and result["daily_status"] in ("SUCCESS", "SKIPPED"):
            data  = get_score(game_date) if result["daily_status"] == "SKIPPED" else data
            games = data.get("games", [])
            reg   = [g for g in games if g.get("gameType") == 2
                     and g.get("gameState") in ("OFF", "FINAL", "F")]

            for g in reg:
                gid = g["id"]
                if detail_loaded(cur, gid):
                    continue
                try:
                    landing  = get_landing(gid)
                    boxscore = get_boxscore(gid)
                    insert_game_detail(cur, conn, gid, landing, boxscore)
                    result["details_loaded"] += 1
                    time.sleep(0.2)   # be polite to the NHL API
                except Exception as e:
                    result["errors"].append(f"detail {gid}: {e}")

            if result["details_loaded"]:
                print(f"{LOG_PFX} {game_date}: {result['details_loaded']} game details loaded")

    except Exception as e:
        result["daily_status"] = "ERROR"
        result["errors"].append(str(e))
        print(f"{LOG_PFX} {game_date}: ERROR - {e}")
        try:
            log_result(cur, conn, game_date, 0, 0, "ERROR", str(e)[:4000])
        except Exception:
            pass
    finally:
        cur.close()

    return result


def load_season(season: int, conn) -> dict:
    """Load all finished regular-season game dates for a given season."""
    print(f"\n{LOG_PFX} Loading season {season}...")
    dates  = get_season_dates(season)
    print(f"{LOG_PFX}   Found {len(dates)} game dates with finished regular-season games")

    totals = {"dates": 0, "games": 0, "details": 0, "errors": 0}
    for d in dates:
        r = load_date(d, conn, load_details=True)
        totals["dates"]   += 1
        totals["games"]   += r.get("games_loaded", 0)
        totals["details"] += r.get("details_loaded", 0)
        totals["errors"]  += len(r.get("errors", []))

    return totals


# ── Entry point ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NHL Bronze Layer Loader")
    group  = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--date",             help="Single date YYYY-MM-DD")
    group.add_argument("--season",           type=int, help="Season e.g. 20252026")
    group.add_argument("--backfill-seasons", action="store_true",
                       help=f"Load all available seasons: {AVAILABLE_SEASONS}")
    parser.add_argument("--no-details",      action="store_true",
                       help="Skip per-game detail fetch (daily summary only)")
    args = parser.parse_args()

    print("=" * 60)
    print("NHL BRONZE LOADER")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60)

    conn = get_connection("bronze")

    if args.date:
        r = load_date(args.date, conn, load_details=not args.no_details)
        print(f"\nDone: {r}")

    elif args.season:
        t = load_season(args.season, conn)
        print(f"\nSeason {args.season} totals: {t}")

    elif args.backfill_seasons:
        grand = {"dates": 0, "games": 0, "details": 0, "errors": 0}
        for season in AVAILABLE_SEASONS:
            t = load_season(season, conn)
            for k in grand:
                grand[k] += t[k]
        print(f"\nAll seasons totals: {grand}")

    conn.close()
    print(f"\nFinished: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
