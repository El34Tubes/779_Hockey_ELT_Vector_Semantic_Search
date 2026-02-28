"""
Raw Ingestion Performance Benchmark
=====================================
Measures INSERT throughput for two approaches:

  v1 pattern: CLOB (json.dumps() string) — bronze_schema design
  v2 pattern: native JSON OSON (Python dict) — bronze_2 design

Uses payloads already in bronze_2.bronze_nhl_landing so the JSON size
is identical across both tests. Runs N rounds and averages.

Also reports historical throughput from the bronze_ingestion_log tables
in each schema.

Usage:
  python exploration/ingest_bench.py
  python exploration/ingest_bench.py --rounds 200
"""

import sys, os, json, time, argparse
from datetime import datetime
from decimal import Decimal


class _OracleEncoder(json.JSONEncoder):
    """json.dumps encoder that handles Oracle Decimal and datetime types."""
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        if isinstance(o, (datetime,)):
            return o.isoformat()
        return super().default(o)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import oracledb
from config.db_connect import get_connection


# ── Helpers ───────────────────────────────────────────────────

def hr(label=""):
    print(f"\n{'─' * 65}")
    if label:
        print(f"  {label}")
        print(f"{'─' * 65}")


def section(title):
    print(f"\n{'=' * 65}")
    print(f"  {title}")
    print(f"{'=' * 65}")


# ── 1. Historical throughput from ingestion logs ──────────────

def historical_throughput(c1, c2):
    section("1. HISTORICAL INGESTION LOG THROUGHPUT")

    # v1: bronze_ingestion_log in bronze_schema
    print("\n  Schema v1 (bronze_schema) — from bronze_ingestion_log:")
    print(f"  {'Source':<20} {'Rows':>8} {'Start':>28} {'End':>28}")
    print(f"  {'-'*20} {'-'*8} {'-'*28} {'-'*28}")
    try:
        c1.execute("""
            SELECT source,
                   SUM(records_inserted)        AS total_rows,
                   MIN(logged_at)            AS first_load,
                   MAX(logged_at)            AS last_load,
                   COUNT(*)                  AS batches
            FROM bronze_ingestion_log
            WHERE status = 'SUCCESS'
            GROUP BY source
            ORDER BY first_load
        """)
        for r in c1.fetchall():
            print(f"  {r[0]:<20} {r[1]:>8,} {str(r[2]):>28} {str(r[3]):>28}")
    except Exception as e:
        print(f"  ERROR: {e}")

    # v2: bronze_ingestion_log in bronze_2
    print("\n  Schema v2 (bronze_2) — from bronze_ingestion_log:")
    print(f"  {'Source':<20} {'Rows':>8} {'Start':>28} {'End':>28}")
    print(f"  {'-'*20} {'-'*8} {'-'*28} {'-'*28}")
    try:
        c2.execute("""
            SELECT source,
                   SUM(records_inserted)        AS total_rows,
                   MIN(logged_at)            AS first_load,
                   MAX(logged_at)            AS last_load,
                   COUNT(*)                  AS batches
            FROM bronze_ingestion_log
            WHERE status = 'SUCCESS'
            GROUP BY source
            ORDER BY first_load
        """)
        for r in c2.fetchall():
            print(f"  {r[0]:<20} {r[1]:>8,} {str(r[2]):>28} {str(r[3]):>28}")
    except Exception as e:
        print(f"  ERROR: {e}")


# ── 2. Micro-benchmark: CLOB vs OSON INSERT ───────────────────

TEMP_CLOB = "bench_clob_tmp"
TEMP_OSON = "bench_oson_tmp"


def setup_bench_tables(conn):
    """Create temporary benchmark tables — drop first if they exist."""
    cur = conn.cursor()
    for tbl in (TEMP_CLOB, TEMP_OSON):
        try:
            cur.execute(f"DROP TABLE {tbl} PURGE")
        except Exception:
            pass

    cur.execute(f"""
        CREATE TABLE {TEMP_CLOB} (
            row_id      NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            game_id     NUMBER,
            raw_clob    CLOB CHECK (raw_clob IS JSON)
        )
    """)
    cur.execute(f"""
        CREATE TABLE {TEMP_OSON} (
            row_id      NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            game_id     NUMBER,
            raw_json    JSON
        )
    """)
    conn.commit()
    cur.close()


def teardown_bench_tables(conn):
    cur = conn.cursor()
    for tbl in (TEMP_CLOB, TEMP_OSON):
        try:
            cur.execute(f"DROP TABLE {tbl} PURGE")
        except Exception:
            pass
    conn.commit()
    cur.close()


def load_sample_payloads(c2, n):
    """Pull n game landing payloads from bronze_2 (returns list of (game_id, dict))."""
    c2.execute(f"""
        SELECT game_id, raw_response
        FROM   bronze_nhl_landing
        WHERE  ROWNUM <= :1
        ORDER BY game_id
    """, (n,))
    rows = c2.fetchall()
    # raw_response comes back as a Python dict (OSON auto-deserialized by oracledb)
    return [(r[0], r[1]) for r in rows]


def bench_clob_insert(conn, payloads):
    """Time inserting payloads as CLOB (json.dumps string) — simulates v1."""
    cur = conn.cursor()
    cur.setinputsizes(None, oracledb.DB_TYPE_CLOB)

    t0 = time.perf_counter()
    for game_id, payload in payloads:
        cur.execute(
            f"INSERT INTO {TEMP_CLOB} (game_id, raw_clob) VALUES (:1, :2)",
            (game_id, json.dumps(payload, cls=_OracleEncoder))   # dict → string → CLOB
        )
    conn.commit()
    return time.perf_counter() - t0


def bench_oson_insert(conn, payloads):
    """Time inserting payloads as native JSON OSON (Python dict) — simulates v2."""
    cur = conn.cursor()
    cur.setinputsizes(None, oracledb.DB_TYPE_JSON)

    t0 = time.perf_counter()
    for game_id, payload in payloads:
        cur.execute(
            f"INSERT INTO {TEMP_OSON} (game_id, raw_json) VALUES (:1, :2)",
            (game_id, payload)                 # dict bound directly as OSON
        )
    conn.commit()
    return time.perf_counter() - t0


def run_micro_benchmark(conn_v2, rounds, sample_n):
    section(f"2. MICRO-BENCHMARK: CLOB vs OSON INSERT ({rounds} rounds × {sample_n} rows)")

    print(f"\n  Loading {sample_n} game payloads from bronze_2.bronze_nhl_landing...")
    c2 = conn_v2.cursor()
    payloads = load_sample_payloads(c2, sample_n)
    c2.close()

    if not payloads:
        print("  ERROR: no payloads found — is bronze_2 backfill complete?")
        return

    # Estimate average payload size
    sample_sizes = [len(json.dumps(p, cls=_OracleEncoder)) for _, p in payloads[:5]]
    avg_kb = sum(sample_sizes) / len(sample_sizes) / 1024
    print(f"  Avg JSON payload size: {avg_kb:.1f} KB per game")

    print(f"\n  Running {rounds} rounds (each round = {sample_n} inserts + commit)...")

    clob_times = []
    oson_times = []

    for i in range(rounds):
        # Alternate CLOB/OSON and truncate between rounds to avoid data growth
        conn_tmp = get_connection("bronze_2")
        setup_bench_tables(conn_tmp)

        try:
            t_clob = bench_clob_insert(conn_tmp, payloads)
            # Truncate CLOB table, then test OSON in same table space
            cur = conn_tmp.cursor()
            cur.execute(f"TRUNCATE TABLE {TEMP_CLOB}")
            cur.close()

            t_oson = bench_oson_insert(conn_tmp, payloads)

            clob_times.append(t_clob)
            oson_times.append(t_oson)

            if (i + 1) % 10 == 0 or i == 0:
                print(f"  Round {i+1:>3}: CLOB={t_clob*1000:6.1f}ms  OSON={t_oson*1000:6.1f}ms")
        finally:
            teardown_bench_tables(conn_tmp)
            conn_tmp.close()

    # Stats
    import statistics
    clob_avg  = statistics.mean(clob_times) * 1000
    oson_avg  = statistics.mean(oson_times) * 1000
    clob_med  = statistics.median(clob_times) * 1000
    oson_med  = statistics.median(oson_times) * 1000
    clob_min  = min(clob_times) * 1000
    oson_min  = min(oson_times) * 1000

    speedup_avg = clob_avg / oson_avg if oson_avg > 0 else float('inf')
    speedup_med = clob_med / oson_med if oson_med > 0 else float('inf')

    hr("Results")
    print(f"\n  {'Metric':<20} {'CLOB (v1)':>12} {'OSON (v2)':>12} {'Speedup':>10}")
    print(f"  {'-'*20} {'-'*12} {'-'*12} {'-'*10}")
    print(f"  {'Avg (ms)':<20} {clob_avg:>12.1f} {oson_avg:>12.1f} {speedup_avg:>9.2f}x")
    print(f"  {'Median (ms)':<20} {clob_med:>12.1f} {oson_med:>12.1f} {speedup_med:>9.2f}x")
    print(f"  {'Best (ms)':<20} {clob_min:>12.1f} {oson_min:>12.1f}")

    print(f"\n  Per-row throughput ({sample_n} rows per batch):")
    clob_rps = sample_n / (clob_avg / 1000)
    oson_rps = sample_n / (oson_avg / 1000)
    print(f"  {'CLOB (v1)':<20} {clob_rps:>10,.0f} rows/sec")
    print(f"  {'OSON (v2)':<20} {oson_rps:>10,.0f} rows/sec")
    print(f"\n  OSON is {speedup_avg:.2f}x faster on average for raw JSON ingestion")

    # Extrapolate to full dataset
    total_games = 4089  # v1 final count
    clob_total_est = (clob_avg / 1000) * (total_games / sample_n)
    oson_total_est = (oson_avg / 1000) * (total_games / sample_n)
    print(f"\n  Estimated time to ingest {total_games:,} games:")
    print(f"  {'CLOB (v1)':<20} {clob_total_est:>8.1f} sec  ({clob_total_est/60:.1f} min)")
    print(f"  {'OSON (v2)':<20} {oson_total_est:>8.1f} sec  ({oson_total_est/60:.1f} min)")

    print(f"\n  NOTE: Real ETL time also includes API latency (~0.2s/game),")
    print(f"        which dominates over storage cost. Pure INSERT overhead above.")


# ── Main ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Bronze ingestion benchmark")
    parser.add_argument("--rounds",   type=int, default=20,
                        help="Number of benchmark rounds (default 20)")
    parser.add_argument("--sample-n", type=int, default=50,
                        help="Number of game records per round (default 50)")
    args = parser.parse_args()

    print("=" * 65)
    print("BRONZE INGESTION PERFORMANCE BENCHMARK")
    print(f"Run at: {datetime.now().isoformat()}")
    print("=" * 65)
    print()
    print("  v1 pattern: json.dumps() → CLOB string (CHECK IS JSON constraint)")
    print("  v2 pattern: Python dict  → native OSON (JSON column type)")
    print()
    print("  Both use the same JSON payloads (game landing data from bronze_2).")
    print("  The CLOB test simulates v1's serialization + bind overhead.")

    conn1 = get_connection("bronze")
    conn2 = get_connection("bronze_2")
    c1    = conn1.cursor()
    c2    = conn2.cursor()

    try:
        historical_throughput(c1, c2)
    finally:
        c1.close()
        c2.close()
        conn1.close()
        conn2.close()

    conn2 = get_connection("bronze_2")
    try:
        run_micro_benchmark(conn2, rounds=args.rounds, sample_n=args.sample_n)
    finally:
        conn2.close()

    print(f"\n{'=' * 65}")
    print(f"Benchmark complete: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
