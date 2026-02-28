"""
Daily Bronze Layer Loader - NHL Semantic Analytics
==================================================
Fetches hockey game data from SportDB API and ingests it into the
Oracle 23ai bronze_hockey_raw table as raw JSON.

Usage:
    python etl/daily_bronze_load.py                  # Load today (offset=0)
    python etl/daily_bronze_load.py --offset -1      # Load yesterday
    python etl/daily_bronze_load.py --backfill       # Load last 7 days

Schedule (Mac/Linux cron - runs daily at 2am):
    0 2 * * * /path/to/venv/bin/python /path/to/etl/daily_bronze_load.py >> /path/to/data/bronze_load.log 2>&1
"""

import sys
import os
import json
import argparse
import hashlib
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import requests
from config.config import Config

# Try modern oracledb first, fall back to cx_Oracle
try:
    import oracledb as cx_Oracle
    ORACLE_THIN_MODE = True
except ImportError:
    try:
        import cx_Oracle
        ORACLE_THIN_MODE = False
    except ImportError:
        cx_Oracle = None
        ORACLE_THIN_MODE = False


# ── Constants ───────────────────────────────────────────────
API_URL    = f"{Config.SPORTDB_BASE_URL}/api/flashscore/hockey/live"
HEADERS    = {'X-API-Key': Config.SPORTDB_API_KEY}
LOG_PREFIX = "[BRONZE_LOAD]"


# ── API ─────────────────────────────────────────────────────

def fetch_games(offset: int = 0) -> list:
    """
    Call SportDB API and return the raw list of game dicts.
    offset: 0=today, -1=yesterday, ... -7=7 days ago (API max depth)
    """
    try:
        resp = requests.get(
            API_URL,
            headers=HEADERS,
            params={'offset': offset, 'tz': Config.TZ_OFFSET},
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()

        if not isinstance(data, list):
            raise ValueError(f"Unexpected API response type: {type(data)}")

        return data

    except requests.HTTPError as e:
        print(f"{LOG_PREFIX} HTTP error fetching offset={offset}: {e}")
        raise
    except Exception as e:
        print(f"{LOG_PREFIX} Error fetching offset={offset}: {e}")
        raise


def offset_to_date(offset: int) -> datetime.date:
    """Convert API day offset to a calendar date."""
    return (datetime.now(timezone.utc) + timedelta(days=offset)).date()


# ── Oracle ──────────────────────────────────────────────────

def get_connection():
    """Return an Oracle DB connection using config credentials."""
    if cx_Oracle is None:
        raise RuntimeError(
            "No Oracle driver found. Install one:\n"
            "  pip install oracledb        (recommended - no Instant Client needed)\n"
            "  pip install cx_Oracle       (requires Oracle Instant Client)"
        )

    if ORACLE_THIN_MODE:
        # python-oracledb thin mode - no Oracle Instant Client required
        oracledb = cx_Oracle
        oracledb.init_oracle_client()  # no-op in thin mode
        conn = oracledb.connect(
            user=Config.ORACLE_USER,
            password=Config.ORACLE_PASSWORD,
            dsn=Config.ORACLE_DSN
        )
    else:
        conn = cx_Oracle.connect(
            Config.ORACLE_USER,
            Config.ORACLE_PASSWORD,
            Config.ORACLE_DSN
        )

    return conn


def already_loaded(cursor, load_date, api_offset: int) -> bool:
    """Return True if this date+offset combo already exists in bronze."""
    cursor.execute(
        "SELECT COUNT(*) FROM bronze_hockey_raw "
        "WHERE load_date = :1 AND api_offset = :2",
        (load_date, api_offset)
    )
    return cursor.fetchone()[0] > 0


def insert_bronze(cursor, load_date, api_offset: int, games: list) -> int:
    """
    Insert one row into bronze_hockey_raw containing the full JSON response.
    Returns the new load_id.
    """
    raw_json = json.dumps(games, ensure_ascii=False)
    game_count = len(games)

    cursor.execute(
        """
        INSERT INTO bronze_hockey_raw
            (load_date, api_offset, game_count, raw_response)
        VALUES (:1, :2, :3, :4)
        RETURNING load_id INTO :5
        """,
        (load_date, api_offset, game_count, raw_json,
         cursor.var(cx_Oracle.NUMBER if not ORACLE_THIN_MODE else int))
    )

    load_id = cursor.bindvars[4].getvalue()
    return int(load_id[0]) if isinstance(load_id, list) else int(load_id)


def call_log_procedure(cursor, load_date, api_offset, games_fetched,
                        games_inserted, status, message=None):
    """Call the Oracle bronze_log_ingestion stored procedure."""
    cursor.callproc(
        'bronze_log_ingestion',
        [load_date, api_offset, games_fetched, games_inserted,
         status, message or '']
    )


# ── Core load logic ─────────────────────────────────────────

def load_day(offset: int, conn) -> dict:
    """
    Load one day's worth of hockey data into Oracle bronze layer.
    Returns a result dict with status and counts.
    """
    load_date = offset_to_date(offset)
    result = {
        'date': str(load_date),
        'offset': offset,
        'games_fetched': 0,
        'games_inserted': 0,
        'status': 'PENDING'
    }

    print(f"\n{LOG_PREFIX} Loading offset={offset} ({load_date})")

    cursor = conn.cursor()

    try:
        # Skip if already loaded
        if already_loaded(cursor, load_date, offset):
            print(f"{LOG_PREFIX}   SKIPPED - already loaded for {load_date}")
            result['status'] = 'SKIPPED'
            call_log_procedure(cursor, load_date, offset, 0, 0,
                               'SKIPPED', f'Already loaded for {load_date}')
            conn.commit()
            return result

        # Fetch from API
        games = fetch_games(offset)
        result['games_fetched'] = len(games)
        print(f"{LOG_PREFIX}   Fetched {len(games)} games from API")

        if not games:
            print(f"{LOG_PREFIX}   WARNING: 0 games returned - skipping insert")
            result['status'] = 'EMPTY'
            call_log_procedure(cursor, load_date, offset, 0, 0,
                               'EMPTY', 'API returned 0 games')
            conn.commit()
            return result

        # Insert into Oracle
        load_id = insert_bronze(cursor, load_date, offset, games)
        conn.commit()

        result['games_inserted'] = len(games)
        result['status'] = 'SUCCESS'
        result['load_id'] = load_id

        print(f"{LOG_PREFIX}   Inserted load_id={load_id} with {len(games)} games")

        # Log the success
        call_log_procedure(cursor, load_date, offset, len(games), len(games),
                           'SUCCESS', f'load_id={load_id}')
        conn.commit()

    except Exception as e:
        conn.rollback()
        result['status'] = 'ERROR'
        result['error'] = str(e)
        print(f"{LOG_PREFIX}   ERROR: {e}")

        try:
            call_log_procedure(cursor, load_date, offset,
                               result['games_fetched'], 0,
                               'ERROR', str(e)[:4000])
            conn.commit()
        except Exception:
            pass

    finally:
        cursor.close()

    return result


# ── Entry point ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Daily Bronze layer loader for SportDB hockey data'
    )
    parser.add_argument(
        '--offset', type=int, default=0,
        help='Day offset: 0=today, -1=yesterday, -7=7 days ago (default: 0)'
    )
    parser.add_argument(
        '--backfill', action='store_true',
        help='Load all 7 available days (offset -7 through 0)'
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Fetch from API and print counts but do not write to Oracle'
    )
    args = parser.parse_args()

    print("=" * 60)
    print("BRONZE LAYER DAILY LOAD")
    print(f"Run time: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    # Validate config
    try:
        if not Config.SPORTDB_API_KEY:
            raise ValueError("SPORTDB_API_KEY not set in .env")
        if not args.dry_run and not Config.ORACLE_PASSWORD:
            raise ValueError("ORACLE_PASSWORD not set in .env")
    except ValueError as e:
        print(f"Config error: {e}")
        sys.exit(1)

    # Dry-run mode - just test the API
    if args.dry_run:
        offsets = list(range(-7, 1)) if args.backfill else [args.offset]
        for offset in offsets:
            games = fetch_games(offset)
            date = offset_to_date(offset)
            print(f"DRY-RUN offset={offset} ({date}): {len(games)} games")
        return

    # Connect to Oracle
    print(f"\nConnecting to Oracle: {Config.ORACLE_DSN}")
    try:
        conn = get_connection()
        print("Oracle connection OK")
    except Exception as e:
        print(f"Oracle connection failed: {e}")
        print("\nTo run without Oracle (API test only), use --dry-run")
        sys.exit(1)

    # Determine which days to load
    offsets = list(range(-7, 1)) if args.backfill else [args.offset]

    results = []
    for offset in offsets:
        result = load_day(offset, conn)
        results.append(result)

    conn.close()

    # Summary
    print("\n" + "=" * 60)
    print("LOAD SUMMARY")
    print("=" * 60)
    success = sum(1 for r in results if r['status'] == 'SUCCESS')
    skipped = sum(1 for r in results if r['status'] == 'SKIPPED')
    errors  = sum(1 for r in results if r['status'] == 'ERROR')
    total_games = sum(r.get('games_inserted', 0) for r in results)

    for r in results:
        print(f"  {r['date']} (offset={r['offset']:3d}): "
              f"{r['status']:8s} | {r.get('games_inserted', 0):4d} games inserted")

    print(f"\nTotal: {success} success, {skipped} skipped, {errors} errors")
    print(f"Games inserted this run: {total_games}")

    sys.exit(1 if errors > 0 else 0)


if __name__ == "__main__":
    main()
