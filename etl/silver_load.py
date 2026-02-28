"""
Silver Layer ETL - Orchestrator
================================
Calls sp_load_silver stored procedure to transform bronze_2 JSON → silver tables.

Architecture:
  - All transformation logic lives in Oracle stored procedures (sql/silver_procedures.sql)
  - Python is a thin caller: connect, callproc, report
  - Delta-aware: procedures only process bronze records since last watermark
  - Safe to re-run: MERGE ensures idempotency

Usage:
  python etl/silver_load.py              # delta load (normal daily run)
  python etl/silver_load.py --reset      # reset watermarks then full reload
  python etl/silver_load.py --status     # show watermarks + recent log, no ETL
"""

import sys, os, argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.db_connect import get_connection

LOG_PFX = "[SILVER]"


# ── Status helpers ────────────────────────────────────────────

def show_watermarks(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT source_table, last_bronze_ts, last_run_at, rows_processed
        FROM   silver_watermarks
        ORDER BY source_table
    """)
    rows = cur.fetchall()
    cur.close()

    print(f"\n{'Source Table':<35} {'Last Bronze TS':<28} {'Last Run':<28} {'Runs':>5}")
    print("-" * 100)
    for r in rows:
        wm    = str(r[1]) if r[1] else "NULL (never run)"
        run   = str(r[2]) if r[2] else "-"
        count = r[3] or 0
        print(f"{r[0]:<35} {wm:<28} {run:<28} {count:>5}")


def show_recent_log(conn, minutes=10):
    cur = conn.cursor()
    cur.execute("""
        SELECT source_table, games_processed, rows_inserted, rows_skipped, status,
               NVL(message, ''), logged_at
        FROM   silver_load_log
        WHERE  logged_at >= SYSTIMESTAMP - NUMTODSINTERVAL(:1, 'MINUTE')
        ORDER BY log_id
    """, (minutes,))
    rows = cur.fetchall()
    cur.close()

    if not rows:
        print(f"\n  (no log entries in last {minutes} minutes)")
        return

    print(f"\n{'Table':<30} {'Rows':>7} {'Skip':>6} {'Status':<10} {'Time':<28} Message")
    print("-" * 110)
    for r in rows:
        print(f"{r[0]:<30} {r[1] or 0:>7} {r[3] or 0:>6} {r[4]:<10} {str(r[6]):<28} {(r[5] or '')[:50]}")


# ── Watermark reset ───────────────────────────────────────────

def reset_watermarks(conn):
    cur = conn.cursor()
    cur.execute("UPDATE silver_watermarks SET last_bronze_ts = NULL, rows_processed = 0")
    conn.commit()
    cur.close()
    print(f"{LOG_PFX} All watermarks reset — next run will do a full reload of all bronze data")


# ── Core ETL call ─────────────────────────────────────────────

def run_silver_load(conn):
    cur = conn.cursor()
    try:
        print(f"{LOG_PFX} Calling sp_load_silver ...")
        t0 = datetime.now()

        cur.callproc("sp_load_silver")

        elapsed = (datetime.now() - t0).total_seconds()
        print(f"{LOG_PFX} Procedure returned in {elapsed:.1f}s")

        show_recent_log(conn, minutes=2)

    except Exception as e:
        print(f"{LOG_PFX} ERROR: {e}")
        raise
    finally:
        cur.close()


# ── Entry point ───────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Silver ETL Orchestrator")
    parser.add_argument("--reset",  action="store_true",
                        help="Reset all watermarks before running (forces full reload)")
    parser.add_argument("--status", action="store_true",
                        help="Show watermarks and recent log only — no ETL")
    args = parser.parse_args()

    print("=" * 60)
    print("SILVER ETL LOADER")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60)

    conn = get_connection("silver")

    if args.status:
        show_watermarks(conn)
        show_recent_log(conn, minutes=60)
        conn.close()
        return

    if args.reset:
        reset_watermarks(conn)

    show_watermarks(conn)
    print()

    run_silver_load(conn)

    print(f"\n{LOG_PFX} Watermarks after run:")
    show_watermarks(conn)

    conn.close()
    print(f"\nFinished: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
