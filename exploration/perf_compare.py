"""
Bronze v1 vs v2 Performance Comparison
========================================
Compares storage, insert characteristics, and JSON query performance
between the original bronze_schema (CLOB, parsed columns) and the
redesigned bronze_2 (native JSON OSON, 1 table per endpoint, raw only).

Usage:
  python exploration/perf_compare.py
"""

import sys, os, time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.db_connect import get_connection


def hr(label=""):
    print(f"\n{'─' * 60}")
    if label:
        print(f"  {label}")
        print(f"{'─' * 60}")


def section(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


# ── 1. Row counts ─────────────────────────────────────────────

def compare_row_counts(c1, c2):
    section("1. ROW COUNTS")

    v1_tables = [
        ("bronze_nhl_daily",      "NHL score (daily)"),
        ("bronze_nhl_game_detail","NHL landing+boxscore merged"),
        ("bronze_espn_daily",     "ESPN scoreboard"),
        ("bronze_sportdb_daily",  "SportDB flashscore"),
    ]
    v2_tables = [
        ("bronze_nhl_score",          "NHL score (daily)"),
        ("bronze_nhl_landing",        "NHL landing (per game)"),
        ("bronze_nhl_boxscore",       "NHL boxscore (per game)"),
        ("bronze_espn_scoreboard",    "ESPN scoreboard"),
        ("bronze_sportdb_flashscore", "SportDB flashscore"),
    ]

    print(f"\n{'Schema v1 (bronze_schema — CLOB, parsed columns)':}")
    print(f"  {'Table':<30} {'Rows':>10}")
    print(f"  {'-'*30} {'-'*10}")
    for tbl, label in v1_tables:
        try:
            c1.execute(f"SELECT COUNT(*) FROM {tbl}")
            n = c1.fetchone()[0]
            print(f"  {tbl:<30} {n:>10,}")
        except Exception as e:
            print(f"  {tbl:<30} {'ERROR':>10}  ({e})")

    print(f"\n{'Schema v2 (bronze_2 — native JSON OSON, raw only)':}")
    print(f"  {'Table':<30} {'Rows':>10}")
    print(f"  {'-'*30} {'-'*10}")
    for tbl, label in v2_tables:
        try:
            c2.execute(f"SELECT COUNT(*) FROM {tbl}")
            n = c2.fetchone()[0]
            print(f"  {tbl:<30} {n:>10,}")
        except Exception as e:
            print(f"  {tbl:<30} {'ERROR':>10}  ({e})")


# ── 2. Storage footprint ──────────────────────────────────────

def compare_storage(c1, c2):
    section("2. STORAGE FOOTPRINT (USER_SEGMENTS)")

    q = """
        SELECT segment_name, ROUND(bytes / 1024 / 1024, 2) AS mb
        FROM user_segments
        WHERE segment_type = 'TABLE'
        ORDER BY bytes DESC
    """

    print(f"\n  Schema v1 (bronze_schema):")
    print(f"  {'Table':<35} {'MB':>8}")
    print(f"  {'-'*35} {'-'*8}")
    c1.execute(q)
    v1_total = 0
    for row in c1.fetchall():
        print(f"  {row[0]:<35} {row[1]:>8.2f}")
        v1_total += row[1]
    print(f"  {'TOTAL':<35} {v1_total:>8.2f}")

    print(f"\n  Schema v2 (bronze_2):")
    print(f"  {'Table':<35} {'MB':>8}")
    print(f"  {'-'*35} {'-'*8}")
    c2.execute(q)
    v2_total = 0
    for row in c2.fetchall():
        print(f"  {row[0]:<35} {row[1]:>8.2f}")
        v2_total += row[1]
    print(f"  {'TOTAL':<35} {v2_total:>8.2f}")

    if v1_total > 0:
        pct = ((v1_total - v2_total) / v1_total) * 100
        print(f"\n  Storage delta: v2 is {abs(pct):.1f}% {'smaller' if pct > 0 else 'larger'} than v1")


# ── 3. JSON query performance (JSON_TABLE) ────────────────────

def time_query(cur, label, sql, params=None):
    start = time.perf_counter()
    if params:
        cur.execute(sql, params)
    else:
        cur.execute(sql)
    rows = cur.fetchall()
    elapsed = time.perf_counter() - start
    print(f"  {label:<45} {elapsed*1000:>8.1f} ms  ({len(rows):,} rows)")
    return elapsed, len(rows)


def compare_query_perf(c1, c2):
    section("3. JSON QUERY PERFORMANCE")

    # Query: extract three stars from landing JSON (one season)
    q_three_stars_v1 = """
        SELECT d.game_id, s.*
        FROM bronze_nhl_game_detail d,
            JSON_TABLE(d.landing_json, '$.summary.threeStars[*]'
                COLUMNS (
                    star_rank    NUMBER        PATH '$.star',
                    player_name  VARCHAR2(100) PATH '$.name.default',
                    team_abbrev  VARCHAR2(10)  PATH '$.teamAbbrev',
                    goals        NUMBER        PATH '$.goals',
                    assists      NUMBER        PATH '$.assists'
                )
            ) s
        WHERE d.season = 20252026
          AND d.landing_json IS NOT NULL
    """

    q_three_stars_v2 = """
        SELECT d.game_id, s.*
        FROM bronze_nhl_landing d,
            JSON_TABLE(d.raw_response, '$.summary.threeStars[*]'
                COLUMNS (
                    star_rank    NUMBER        PATH '$.star',
                    player_name  VARCHAR2(100) PATH '$.name.default',
                    team_abbrev  VARCHAR2(10)  PATH '$.teamAbbrev',
                    goals        NUMBER        PATH '$.goals',
                    assists      NUMBER        PATH '$.assists'
                )
            ) s
        WHERE d.game_date >= DATE '2025-10-01'
          AND d.raw_response IS NOT NULL
    """

    # Query: count games per team (score summaries)
    q_team_count_v1 = """
        SELECT g.home_team_abbrev, COUNT(*) AS games
        FROM bronze_nhl_daily d,
            JSON_TABLE(d.raw_response, '$.games[*]'
                COLUMNS (home_team_abbrev VARCHAR2(10) PATH '$.homeTeam.abbrev',
                         game_type NUMBER PATH '$.gameType')
            ) g
        WHERE g.game_type = 2
        GROUP BY g.home_team_abbrev
        ORDER BY games DESC
    """

    q_team_count_v2 = """
        SELECT g.home_team_abbrev, COUNT(*) AS games
        FROM bronze_nhl_score d,
            JSON_TABLE(d.raw_response, '$.games[*]'
                COLUMNS (home_team_abbrev VARCHAR2(10) PATH '$.homeTeam.abbrev',
                         game_type NUMBER PATH '$.gameType')
            ) g
        WHERE g.game_type = 2
        GROUP BY g.home_team_abbrev
        ORDER BY games DESC
    """

    hr("Three Stars extraction (JSON_TABLE) — current season")
    t1a, r1a = time_query(c1, "v1 CLOB  (bronze_nhl_game_detail.landing_json)", q_three_stars_v1)
    t2a, r2a = time_query(c2, "v2 OSON  (bronze_nhl_landing.raw_response)",     q_three_stars_v2)
    if t1a > 0:
        speedup = t1a / t2a if t2a > 0 else float('inf')
        print(f"\n  Speedup: v2 is {speedup:.2f}x {'faster' if speedup > 1 else 'slower'}")

    hr("Games per home team (JSON_TABLE, all seasons)")
    t1b, r1b = time_query(c1, "v1 CLOB  (bronze_nhl_daily.raw_response)",  q_team_count_v1)
    t2b, r2b = time_query(c2, "v2 OSON  (bronze_nhl_score.raw_response)",   q_team_count_v2)
    if t1b > 0:
        speedup = t1b / t2b if t2b > 0 else float('inf')
        print(f"\n  Speedup: v2 is {speedup:.2f}x {'faster' if speedup > 1 else 'slower'}")


# ── 4. Column structure comparison ────────────────────────────

def compare_columns(c1, c2):
    section("4. COLUMN STRUCTURE — BRONZE DESIGN COMPARISON")

    tables_v1 = ['BRONZE_NHL_DAILY', 'BRONZE_NHL_GAME_DETAIL']
    tables_v2 = ['BRONZE_NHL_SCORE', 'BRONZE_NHL_LANDING', 'BRONZE_NHL_BOXSCORE']

    print(f"\n  v1 tables (parsed columns + JSON CLOB):")
    for t in tables_v1:
        c1.execute(
            "SELECT column_name, data_type, data_length FROM user_tab_columns "
            "WHERE table_name = :1 ORDER BY column_id", (t,)
        )
        cols = c1.fetchall()
        print(f"\n  {t} ({len(cols)} columns):")
        for col in cols:
            print(f"    {col[0]:<25} {col[1]}")

    print(f"\n  v2 tables (raw JSON OSON only):")
    for t in tables_v2:
        c2.execute(
            "SELECT column_name, data_type, data_length FROM user_tab_columns "
            "WHERE table_name = :1 ORDER BY column_id", (t,)
        )
        cols = c2.fetchall()
        print(f"\n  {t} ({len(cols)} columns):")
        for col in cols:
            print(f"    {col[0]:<25} {col[1]}")


# ── Main ──────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("BRONZE v1 vs v2 PERFORMANCE COMPARISON")
    print(f"Run at: {datetime.now().isoformat()}")
    print("=" * 60)
    print()
    print("  v1: bronze_schema  — CLOB JSON, parsed columns, merged endpoints")
    print("  v2: bronze_2       — native JSON OSON, raw only, 1 table per endpoint")

    conn1 = get_connection("bronze")
    conn2 = get_connection("bronze_2")
    c1    = conn1.cursor()
    c2    = conn2.cursor()

    try:
        compare_row_counts(c1, c2)
        compare_storage(c1, c2)
        compare_columns(c1, c2)
        compare_query_perf(c1, c2)
    finally:
        c1.close()
        c2.close()
        conn1.close()
        conn2.close()

    print(f"\n{'=' * 60}")
    print(f"Comparison complete: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
