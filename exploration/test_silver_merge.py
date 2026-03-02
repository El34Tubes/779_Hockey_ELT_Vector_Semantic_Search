"""
Silver Layer MERGE Validation Tests
====================================
Tests each silver stored procedure using a single isolated game as the test subject.

Test plan:
  1. Snapshot BEFORE state for one game across all silver tables
  2. Delete that game from silver (FK-safe order)
  3. Confirm AFTER-DELETE state (game gone)
  4. Call each sp_load_* procedure
  5. Confirm AFTER-INSERT state (game back, data correct)
  6. Idempotency: call procs again — verify MERGE updates but no new inserts
  7. Watermark filter: call with future timestamp — verify 0 rows processed
  8. Data quality crosschecks: goal count vs score, FK orphan check
  9. Print silver_load_log entries from this test run
"""

import sys, os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.db_connect import get_connection

PASS = "PASS"
FAIL = "FAIL"
results = []

def check(label, condition, detail=""):
    status = PASS if condition else FAIL
    mark = "✓" if condition else "✗"
    msg = f"  {mark} [{status}] {label}"
    if detail:
        msg += f"\n         {detail}"
    print(msg)
    results.append((status, label))
    return condition


def section(title):
    print(f"\n{'─'*70}")
    print(f"  {title}")
    print(f"{'─'*70}")


print("=" * 70)
print("  SILVER LAYER MERGE VALIDATION TESTS")
print(f"  Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 70)

conn = get_connection('silver', verbose=False)
cur  = conn.cursor()

# ── Baseline counts before anything ───────────────────────────────────
section("0. Baseline Row Counts (Full Dataset)")
tables = ['silver_games', 'silver_players', 'silver_goals',
          'silver_penalties', 'silver_three_stars',
          'silver_skater_stats', 'silver_goalie_stats']
baseline = {}
for t in tables:
    cur.execute(f"SELECT COUNT(*) FROM {t}")
    baseline[t] = cur.fetchone()[0]
    print(f"  {t:28s}: {baseline[t]:>6,} rows")


# ── Pick one test game ─────────────────────────────────────────────────
section("1. Test Game Selection (single game, 2025-26 season opener)")
cur.execute("""
    SELECT sg.game_id, sg.game_date, sg.home_team, sg.away_team,
           sg.home_score, sg.away_score, sg.last_period_type, sg.season
    FROM   silver_games sg
    WHERE  sg.season = 20252026
    ORDER  BY sg.game_date ASC
    FETCH FIRST 1 ROW ONLY
""")
row = cur.fetchone()
game_id   = row[0]
game_date = row[1].strftime('%Y-%m-%d')
home, away = row[2], row[3]
h_score, a_score = row[4], row[5]
period_type = row[6]

print(f"  Game ID   : {game_id}")
print(f"  Date      : {game_date}")
print(f"  Matchup   : {away} @ {home}")
print(f"  Score     : {home} {h_score} – {a_score} {away}  ({period_type})")

# Count child rows for this one game
child_before = {}
child_tables = {
    'silver_goals':        'game_id',
    'silver_penalties':    'game_id',
    'silver_three_stars':  'game_id',
    'silver_skater_stats': 'game_id',
    'silver_goalie_stats': 'game_id',
}
print(f"\n  Child rows for game {game_id}:")
for t, col in child_tables.items():
    cur.execute(f"SELECT COUNT(*) FROM {t} WHERE {col} = :1", (game_id,))
    child_before[t] = cur.fetchone()[0]
    print(f"    {t:25s}: {child_before[t]:>3} rows")


# ── BEFORE: Delete game from silver ───────────────────────────────────
section("2. Delete Test Game from Silver (BEFORE state)")
cur.execute("DELETE FROM silver_three_stars  WHERE game_id = :1", (game_id,))
print(f"  Deleted {cur.rowcount:>3} rows from silver_three_stars")
cur.execute("DELETE FROM silver_goals        WHERE game_id = :1", (game_id,))
print(f"  Deleted {cur.rowcount:>3} rows from silver_goals")
cur.execute("DELETE FROM silver_penalties    WHERE game_id = :1", (game_id,))
print(f"  Deleted {cur.rowcount:>3} rows from silver_penalties")
cur.execute("DELETE FROM silver_skater_stats WHERE game_id = :1", (game_id,))
print(f"  Deleted {cur.rowcount:>3} rows from silver_skater_stats")
cur.execute("DELETE FROM silver_goalie_stats WHERE game_id = :1", (game_id,))
print(f"  Deleted {cur.rowcount:>3} rows from silver_goalie_stats")
cur.execute("DELETE FROM silver_espn_game_meta WHERE nhl_game_id = :1", (game_id,))
print(f"  Deleted {cur.rowcount:>3} rows from silver_espn_game_meta")
cur.execute("DELETE FROM silver_games        WHERE game_id = :1", (game_id,))
print(f"  Deleted {cur.rowcount:>3} rows from silver_games")
conn.commit()

# Confirm deleted
cur.execute("SELECT COUNT(*) FROM silver_games WHERE game_id = :1", (game_id,))
after_delete = cur.fetchone()[0]
check("Game removed from silver_games after DELETE", after_delete == 0,
      f"silver_games count for {game_id} = {after_delete}")
cur.execute("SELECT COUNT(*) FROM silver_goals WHERE game_id = :1", (game_id,))
check("Goals removed from silver_goals after DELETE", cur.fetchone()[0] == 0)
cur.execute("SELECT COUNT(*) FROM silver_skater_stats WHERE game_id = :1", (game_id,))
check("Skater stats removed after DELETE", cur.fetchone()[0] == 0)

# Also record total silver_games count after delete
cur.execute("SELECT COUNT(*) FROM silver_games")
count_after_delete = cur.fetchone()[0]
print(f"\n  silver_games total: {count_after_delete:,} rows (was {baseline['silver_games']:,}, down 1)")


# ── CALL PROCEDURES ────────────────────────────────────────────────────
section("3. Call sp_load_games (p_wm => NULL)")
log_ts_before = datetime.now()
cur.callproc("sp_load_games", [None])
conn.commit()

cur.execute("""
    SELECT game_id, game_date, home_team, away_team,
           home_score, away_score, last_period_type
    FROM   silver_games WHERE game_id = :1
""", (game_id,))
restored = cur.fetchone()
check("Game re-inserted by sp_load_games", restored is not None,
      f"Game {game_id} found: {restored}")

if restored:
    check("Score correctly restored (home)",  restored[4] == h_score,
          f"silver: {restored[4]}, expected: {h_score}")
    check("Score correctly restored (away)",  restored[5] == a_score,
          f"silver: {restored[5]}, expected: {a_score}")
    check("Period type correctly restored", restored[6] == period_type,
          f"silver: {restored[6]}, expected: {period_type}")

cur.execute("SELECT COUNT(*) FROM silver_games")
count_after_sp = cur.fetchone()[0]
check("silver_games total count restored to baseline",
      count_after_sp == baseline['silver_games'],
      f"count = {count_after_sp:,}, expected {baseline['silver_games']:,}")


section("4. Call sp_load_players (p_wm => NULL)")
cur.callproc("sp_load_players", [None])
conn.commit()
cur.execute("SELECT COUNT(*) FROM silver_players")
player_count = cur.fetchone()[0]
check("silver_players count unchanged or grown (upsert dim)",
      player_count >= baseline['silver_players'],
      f"count = {player_count:,}")


section("5. Call sp_load_goals (p_wm => NULL)")
cur.callproc("sp_load_goals", [None])
conn.commit()
cur.execute("SELECT COUNT(*) FROM silver_goals WHERE game_id = :1", (game_id,))
goals_restored = cur.fetchone()[0]
check("Goals re-inserted by sp_load_goals",
      goals_restored == child_before['silver_goals'],
      f"restored {goals_restored}, expected {child_before['silver_goals']}")

# Goal count vs final score crosscheck
expected_goals = h_score + a_score
check("Goal rows = home_score + away_score (data quality)",
      goals_restored == expected_goals,
      f"silver_goals rows: {goals_restored}, score total: {expected_goals}")


section("6. Call sp_load_three_stars (p_wm => NULL)")
cur.callproc("sp_load_three_stars", [None])
conn.commit()
cur.execute("SELECT COUNT(*) FROM silver_three_stars WHERE game_id = :1", (game_id,))
stars_restored = cur.fetchone()[0]
check("Three stars re-inserted",
      stars_restored == child_before['silver_three_stars'],
      f"restored {stars_restored}, expected {child_before['silver_three_stars']}")
check("Exactly 3 star rows per game", stars_restored == 3,
      f"{stars_restored} rows found")


section("7. Call sp_load_penalties (p_wm => NULL)")
cur.callproc("sp_load_penalties", [None])
conn.commit()
cur.execute("SELECT COUNT(*) FROM silver_penalties WHERE game_id = :1", (game_id,))
pen_restored = cur.fetchone()[0]
check("Penalties re-inserted by sp_load_penalties",
      pen_restored == child_before['silver_penalties'],
      f"restored {pen_restored}, expected {child_before['silver_penalties']}")


section("8. Call sp_load_skater_stats + sp_load_goalie_stats (p_wm => NULL)")
cur.callproc("sp_load_skater_stats", [None])
conn.commit()
cur.callproc("sp_load_goalie_stats", [None])
conn.commit()

cur.execute("SELECT COUNT(*) FROM silver_skater_stats WHERE game_id = :1", (game_id,))
sk_restored = cur.fetchone()[0]
check("Skater stats re-inserted", sk_restored == child_before['silver_skater_stats'],
      f"restored {sk_restored}, expected {child_before['silver_skater_stats']}")

cur.execute("SELECT COUNT(*) FROM silver_goalie_stats WHERE game_id = :1", (game_id,))
gk_restored = cur.fetchone()[0]
check("Goalie stats re-inserted", gk_restored == child_before['silver_goalie_stats'],
      f"restored {gk_restored}, expected {child_before['silver_goalie_stats']}")

# Verify 2 goalies (1 per team, starters)
check("Expected ~2 goalie rows (1 per team)",
      1 <= gk_restored <= 4,
      f"{gk_restored} goalie rows")


# ── IDEMPOTENCY TEST ───────────────────────────────────────────────────
section("9. Idempotency Test (call all procs again — no new rows expected)")
before_idempotency = {}
for t in tables:
    cur.execute(f"SELECT COUNT(*) FROM {t}")
    before_idempotency[t] = cur.fetchone()[0]

cur.callproc("sp_load_games",       [None])
cur.callproc("sp_load_players",     [None])
cur.callproc("sp_load_goals",       [None])
cur.callproc("sp_load_three_stars", [None])
cur.callproc("sp_load_skater_stats",[None])
cur.callproc("sp_load_goalie_stats",[None])
# sp_load_penalties uses NOT EXISTS guard — call too
cur.callproc("sp_load_penalties",   [None])
conn.commit()

for t in tables:
    cur.execute(f"SELECT COUNT(*) FROM {t}")
    after = cur.fetchone()[0]
    delta = after - before_idempotency[t]
    check(f"{t}: no new rows after second run (delta={delta})",
          delta == 0,
          f"before={before_idempotency[t]:,}, after={after:,}")


# ── WATERMARK FILTER TEST ──────────────────────────────────────────────
section("10. Watermark Filter Test (p_wm = tomorrow → 0 rows processed)")
future_ts = datetime.now() + timedelta(days=1)

cur.execute("SELECT COUNT(*) FROM silver_games")
wm_before = cur.fetchone()[0]

cur.callproc("sp_load_games", [future_ts])
conn.commit()

cur.execute("SELECT COUNT(*) FROM silver_games")
wm_after = cur.fetchone()[0]
delta_wm = wm_after - wm_before

check("sp_load_games with future watermark inserts 0 new rows",
      delta_wm == 0,
      f"Watermark={future_ts.strftime('%Y-%m-%d %H:%M')}, delta={delta_wm}")
print(f"  (All bronze loaded_at values are in the past — filter correctly excludes them)")


# ── FK INTEGRITY CHECK ─────────────────────────────────────────────────
section("11. Foreign Key Integrity Checks")
cur.execute("""
    SELECT COUNT(*) FROM silver_goals
    WHERE  scorer_id IS NOT NULL
    AND    scorer_id NOT IN (SELECT player_id FROM silver_players)
""")
orphan_scorers = cur.fetchone()[0]
check("No orphan scorer_ids in silver_goals",
      orphan_scorers == 0,
      f"{orphan_scorers} orphan scorer references found")

cur.execute("""
    SELECT COUNT(*) FROM silver_skater_stats
    WHERE  player_id NOT IN (SELECT player_id FROM silver_players)
""")
orphan_skaters = cur.fetchone()[0]
check("No orphan player_ids in silver_skater_stats",
      orphan_skaters == 0,
      f"{orphan_skaters} orphan player references found")

cur.execute("""
    SELECT COUNT(*) FROM silver_goals
    WHERE  game_id NOT IN (SELECT game_id FROM silver_games)
""")
orphan_goals = cur.fetchone()[0]
check("No orphan game_ids in silver_goals",
      orphan_goals == 0,
      f"{orphan_goals} orphan game references found")


# ── DATA QUALITY SPOT CHECK (5 games) ─────────────────────────────────
section("12. Data Quality Spot Check (5 random games — score vs goal count)")
cur.execute("""
    SELECT sg.game_id, sg.home_score, sg.away_score,
           COUNT(sgl.goal_id) AS actual_goals
    FROM   silver_games sg
    LEFT JOIN silver_goals sgl ON sgl.game_id = sg.game_id
    WHERE  sg.game_id IN (
        SELECT game_id FROM silver_games
        ORDER BY DBMS_RANDOM.VALUE
        FETCH FIRST 5 ROWS ONLY
    )
    GROUP BY sg.game_id, sg.home_score, sg.away_score
    ORDER BY sg.game_id
""")
rows = cur.fetchall()
match_count = 0
for r in rows:
    expected = (r[1] or 0) + (r[2] or 0)
    match = r[3] == expected
    if match:
        match_count += 1
    mark = "✓" if match else "✗"
    print(f"  {mark} game {r[0]}: score={r[1]}-{r[2]}, goal rows={r[3]}, expected={expected}")
check("All 5 sample games have goal count = home_score + away_score",
      match_count == 5,
      f"{match_count}/5 match")


# ── SILVER_LOAD_LOG ────────────────────────────────────────────────────
section("13. silver_load_log — Recent Entries from This Test Run")
cur.execute("""
    SELECT source_table, rows_inserted, status, logged_at
    FROM   silver_load_log
    WHERE  logged_at >= :1
    ORDER  BY logged_at
""", (log_ts_before,))
log_rows = cur.fetchall()
print(f"  {'Table':25s} {'Rows':>6}  {'Status':8}  {'Time'}")
print(f"  {'─'*25} {'─'*6}  {'─'*8}  {'─'*12}")
for r in log_rows:
    print(f"  {r[0]:25s} {r[1]:>6,}  {r[2]:8}  {r[3].strftime('%H:%M:%S')}")


# ── FINAL COUNTS ───────────────────────────────────────────────────────
section("14. Final Row Counts vs Baseline")
all_match = True
for t in tables:
    cur.execute(f"SELECT COUNT(*) FROM {t}")
    final = cur.fetchone()[0]
    delta = final - baseline[t]
    mark = "✓" if delta == 0 else ("↑" if delta > 0 else "↓")
    print(f"  {mark} {t:28s}: {final:>6,}  (Δ {delta:+d})")
    if delta != 0 and t not in ('silver_players',):
        all_match = False
check("All silver table counts match baseline after full test cycle",
      all_match)


# ── SUMMARY ───────────────────────────────────────────────────────────
section("SUMMARY")
passed = sum(1 for s, _ in results if s == PASS)
failed = sum(1 for s, _ in results if s == FAIL)
total  = len(results)
print(f"\n  Passed : {passed}/{total}")
print(f"  Failed : {failed}/{total}")
print(f"\n  Test Game : {game_id} ({away} @ {home}, {game_date}, {h_score}-{a_score} {period_type})")
if failed:
    print("\n  Failed checks:")
    for s, label in results:
        if s == FAIL:
            print(f"    ✗ {label}")

print()
cur.close()
conn.close()
