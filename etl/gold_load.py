"""
Gold Layer ETL - Orchestrator
==============================
Calls sp_load_gold stored procedure to transform silver → gold analytics tables.

Architecture:
  - All transformation logic lives in Oracle stored procedures (sql/gold_procedures.sql)
  - Python is a thin caller: connect, callproc, report
  - Delta-aware: procedures only process silver records since last watermark
  - Vector embeddings: Generated post-ETL by separate script (gold_embed.py)

Usage:
  python etl/gold_load.py              # delta load (normal daily run)
  python etl/gold_load.py --reset      # reset watermarks then full reload
  python etl/gold_load.py --status     # show watermarks + recent log, no ETL
"""

import sys, os, argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.db_connect import get_connection

LOG_PFX = "[GOLD]"


# ── Status helpers ────────────────────────────────────────────

def show_watermarks(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT source_table, last_silver_ts, last_run_at, rows_processed
        FROM   gold_watermarks
        ORDER BY source_table
    """)
    rows = cur.fetchall()
    cur.close()

    print(f"\n{'Source Table':<35} {'Last Silver TS':<28} {'Last Run':<28} {'Runs':>5}")
    print("-" * 100)
    for r in rows:
        wm    = str(r[1]) if r[1] else "NULL (never run)"
        run   = str(r[2]) if r[2] else "-"
        count = r[3] or 0
        print(f"{r[0]:<35} {wm:<28} {run:<28} {count:>5}")


def show_recent_log(conn, minutes=10):
    cur = conn.cursor()
    cur.execute("""
        SELECT source_table, rows_inserted, rows_updated, rows_skipped,
               vectors_generated, status, NVL(message, ''), logged_at
        FROM   gold_load_log
        WHERE  logged_at >= SYSTIMESTAMP - NUMTODSINTERVAL(:1, 'MINUTE')
        ORDER BY log_id
    """, (minutes,))
    rows = cur.fetchall()
    cur.close()

    if not rows:
        print(f"\n  (no log entries in last {minutes} minutes)")
        return

    print(f"\n{'Table':<30} {'Ins':>7} {'Upd':>7} {'Skip':>6} {'Vecs':>6} {'Status':<10} {'Time':<28} Message")
    print("-" * 130)
    for r in rows:
        print(f"{r[0]:<30} {r[1] or 0:>7} {r[2] or 0:>7} {r[3] or 0:>6} {r[4] or 0:>6} {r[5]:<10} {str(r[7]):<28} {(r[6] or '')[:40]}")


# ── Watermark reset ───────────────────────────────────────────

def reset_watermarks(conn):
    cur = conn.cursor()
    cur.execute("UPDATE gold_watermarks SET last_silver_ts = NULL, rows_processed = 0")
    conn.commit()
    cur.close()
    print(f"{LOG_PFX} All watermarks reset — next run will do a full reload of all silver data")


# ── Core ETL call ─────────────────────────────────────────────

def run_gold_load(conn):
    cur = conn.cursor()
    try:
        print(f"{LOG_PFX} Calling sp_load_gold ...")
        t0 = datetime.now()

        cur.callproc("sp_load_gold")

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
    parser = argparse.ArgumentParser(description="Gold ETL Orchestrator")
    parser.add_argument("--reset",  action="store_true",
                        help="Reset all watermarks before running (forces full reload)")
    parser.add_argument("--status", action="store_true",
                        help="Show watermarks and recent log only — no ETL")
    args = parser.parse_args()

    print("=" * 60)
    print("GOLD ETL LOADER")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 60)

    conn = get_connection("gold")

    if args.status:
        show_watermarks(conn)
        show_recent_log(conn, minutes=60)
        conn.close()
        return

    if args.reset:
        reset_watermarks(conn)

    show_watermarks(conn)
    print()

    run_gold_load(conn)

    print(f"\n{LOG_PFX} Watermarks after run:")
    show_watermarks(conn)

    conn.close()
    print(f"\nFinished: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
