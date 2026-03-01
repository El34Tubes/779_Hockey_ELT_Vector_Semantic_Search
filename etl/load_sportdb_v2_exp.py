"""
SportDB Flashscore Loader v2 - Bronze Layer
============================================
Source: api.sportdb.dev  (API key required)

Loads: bronze_sportdb_flashscore  (one row per day offset)

Raw API response stored as native Oracle JSON (OSON). No parsed columns.

Usage:
  python etl/load_sportdb_v2.py
  python etl/load_sportdb_v2.py --backfill
  python etl/load_sportdb_v2.py --offset -3
"""

import sys, os, argparse
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import oracledb
from config.config import Config
from config.db_connect import get_connection

BASE    = f"{Config.SPORTDB_BASE_URL}/api/flashscore/hockey/live"
HEADERS = {"X-API-Key": Config.SPORTDB_API_KEY}
LOG_PFX = "[SPORTDBv2]"


# ── API helpers ───────────────────────────────────────────────

def fetch_games(offset: int) -> list:
    r = requests.get(
        BASE,
        headers=HEADERS,
        params={"offset": offset, "tz": Config.TZ_OFFSET},
        timeout=15
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise ValueError(f"Unexpected response type: {type(data)}")
    return data


def offset_to_date(offset: int):
    return (datetime.now(timezone.utc) + timedelta(days=offset)).date()


# ── Oracle helpers ────────────────────────────────────────────

def already_loaded(cur, game_date, api_offset: int) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM bronze_sportdb_flashscore WHERE game_date = :1 AND api_offset = :2",
        (game_date, api_offset)
    )
    return cur.fetchone()[0] > 0


def insert_sportdb(cur, conn, game_date, api_offset: int, games: list):
    cur.setinputsizes(None, None, oracledb.DB_TYPE_JSON)
    cur.execute(
        "INSERT INTO bronze_sportdb_flashscore (game_date, api_offset, raw_response) VALUES (:1, :2, :3)",
        (game_date, api_offset, games)
    )
    conn.commit()


def log_result(cur, conn, game_date, fetched, inserted, status, msg=None):
    cur.callproc("bronze_log", ["SPORTDB", game_date, fetched, inserted, status, msg or ""])
    conn.commit()


# ── Core loader ───────────────────────────────────────────────

def load_offset(offset: int, conn) -> dict:
    game_date = offset_to_date(offset)
    result    = {"date": str(game_date), "offset": offset, "status": "PENDING", "games": 0}
    cur       = conn.cursor()

    try:
        if already_loaded(cur, game_date, offset):
            print(f"{LOG_PFX} offset={offset} ({game_date}): already loaded, skipping")
            result["status"] = "SKIPPED"
            return result

        games = fetch_games(offset)

        if not games:
            result["status"] = "EMPTY"
            log_result(cur, conn, game_date, 0, 0, "EMPTY")
            return result

        insert_sportdb(cur, conn, game_date, offset, games)
        result.update({"status": "SUCCESS", "games": len(games)})
        log_result(cur, conn, game_date, len(games), len(games), "SUCCESS")
        print(f"{LOG_PFX} offset={offset} ({game_date}): {len(games)} games loaded")

    except Exception as e:
        result["status"] = "ERROR"
        print(f"{LOG_PFX} offset={offset} ({game_date}): ERROR - {e}")
        try:
            log_result(cur, conn, game_date, 0, 0, "ERROR", str(e)[:4000])
        except Exception:
            pass
    finally:
        cur.close()

    return result


# ── Entry point ───────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="SportDB Bronze v2 Loader")
    group  = parser.add_mutually_exclusive_group()
    group.add_argument("--backfill", action="store_true",
                       help="Load all 7 available days")
    group.add_argument("--offset",   type=int, default=0)
    args = parser.parse_args()

    print("=" * 60)
    print("SPORTDB BRONZE v2 LOADER")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60)

    conn    = get_connection("bronze_2")
    offsets = list(range(-7, 1)) if args.backfill else [args.offset]
    results = [load_offset(o, conn) for o in offsets]
    conn.close()

    success = sum(1 for r in results if r["status"] == "SUCCESS")
    games   = sum(r["games"] for r in results)
    print(f"\nDone: {success} loaded | {games} total games")
    print(f"Finished: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
