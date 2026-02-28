#!/usr/bin/env python3
"""
Validate improvements from enhanced narratives
Runs targeted tests that previously had issues and compares results
"""

import oracledb
from config.db_connect import get_connection
from sentence_transformers import SentenceTransformer
import array
import warnings
warnings.filterwarnings('ignore')

def test_blowout_detection():
    """Test improved blowout game detection"""
    print("\n" + "=" * 70)
    print("TEST: Blowout Game Detection")
    print("Query: 'dominant one-sided blowout crushing victory'")
    print("=" * 70)

    conn = get_connection('gold')
    model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')

    query = "dominant one-sided blowout crushing victory"
    query_embedding = model.encode(query)
    vec_array = array.array('f', query_embedding)

    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            home_team_name,
            away_team_name,
            home_score,
            away_score,
            ABS(home_score - away_score) as goal_diff,
            ROUND(VECTOR_DISTANCE(narrative_vector, :vec, COSINE), 4) AS similarity
        FROM gold_game_narratives
        WHERE narrative_vector IS NOT NULL
        ORDER BY VECTOR_DISTANCE(narrative_vector, :vec, COSINE)
        FETCH FIRST 10 ROWS ONLY
    """, {'vec': vec_array})

    results = cursor.fetchall()

    blowouts = sum(1 for r in results if r[4] >= 4)
    avg_diff = sum(r[4] for r in results) / len(results)
    avg_sim = sum(r[5] for r in results) / len(results)

    print(f"\nTop 10 Results:")
    for i, (home, away, hscore, ascore, diff, sim) in enumerate(results, 1):
        winner = home if hscore > ascore else away
        print(f"{i}. {away} @ {home}: {ascore}-{hscore} (Winner: {winner}, Diff: {diff})")
        print(f"   Similarity: {sim}")

    print(f"\nMetrics:")
    print(f"  True blowouts (4+ goal diff): {blowouts}/10 ({blowouts*10}%)")
    print(f"  Average goal differential: {avg_diff:.1f}")
    print(f"  Average similarity: {avg_sim:.4f}")

    cursor.close()
    conn.close()

    return blowouts, avg_diff


def test_defensive_battle():
    """Test improved defensive battle detection"""
    print("\n" + "=" * 70)
    print("TEST: Defensive Battle Detection")
    print("Query: 'defensive battle goaltending duel low scoring tight'")
    print("=" * 70)

    conn = get_connection('gold')
    model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')

    query = "defensive battle goaltending duel low scoring tight"
    query_embedding = model.encode(query)
    vec_array = array.array('f', query_embedding)

    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            home_team_name,
            away_team_name,
            home_score,
            away_score,
            home_score + away_score as total_goals,
            ROUND(VECTOR_DISTANCE(narrative_vector, :vec, COSINE), 4) AS similarity
        FROM gold_game_narratives
        WHERE narrative_vector IS NOT NULL
        ORDER BY VECTOR_DISTANCE(narrative_vector, :vec, COSINE)
        FETCH FIRST 10 ROWS ONLY
    """, {'vec': vec_array})

    results = cursor.fetchall()

    low_scoring = sum(1 for r in results if r[4] <= 3)
    avg_goals = sum(r[4] for r in results) / len(results)
    avg_sim = sum(r[5] for r in results) / len(results)

    print(f"\nTop 10 Results:")
    for i, (home, away, hscore, ascore, total, sim) in enumerate(results, 1):
        print(f"{i}. {away} @ {home}: {ascore}-{hscore} (Total: {total})")
        print(f"   Similarity: {sim}")

    print(f"\nMetrics:")
    print(f"  Low-scoring games (≤3 goals): {low_scoring}/10 ({low_scoring*10}%)")
    print(f"  Average total goals: {avg_goals:.1f}")
    print(f"  Average similarity: {avg_sim:.4f}")

    cursor.close()
    conn.close()

    return low_scoring, avg_goals


def test_high_scoring():
    """Test offensive shootout detection"""
    print("\n" + "=" * 70)
    print("TEST: Offensive Shootout Detection")
    print("Query: 'offensive shootout high scoring many goals back and forth'")
    print("=" * 70)

    conn = get_connection('gold')
    model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')

    query = "offensive shootout high scoring many goals back and forth"
    query_embedding = model.encode(query)
    vec_array = array.array('f', query_embedding)

    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            home_team_name,
            away_team_name,
            home_score,
            away_score,
            home_score + away_score as total_goals,
            ROUND(VECTOR_DISTANCE(narrative_vector, :vec, COSINE), 4) AS similarity
        FROM gold_game_narratives
        WHERE narrative_vector IS NOT NULL
        ORDER BY VECTOR_DISTANCE(narrative_vector, :vec, COSINE)
        FETCH FIRST 10 ROWS ONLY
    """, {'vec': vec_array})

    results = cursor.fetchall()

    high_scoring = sum(1 for r in results if r[4] >= 7)
    avg_goals = sum(r[4] for r in results) / len(results)
    avg_sim = sum(r[5] for r in results) / len(results)

    print(f"\nTop 10 Results:")
    for i, (home, away, hscore, ascore, total, sim) in enumerate(results, 1):
        print(f"{i}. {away} @ {home}: {ascore}-{hscore} (Total: {total})")
        print(f"   Similarity: {sim}")

    print(f"\nMetrics:")
    print(f"  High-scoring games (≥7 goals): {high_scoring}/10 ({high_scoring*10}%)")
    print(f"  Average total goals: {avg_goals:.1f}")
    print(f"  Average similarity: {avg_sim:.4f}")

    cursor.close()
    conn.close()

    return high_scoring, avg_goals


def test_elite_players():
    """Test elite player detection with new narratives"""
    print("\n" + "=" * 70)
    print("TEST: Elite Player Detection")
    print("Query: 'elite superstar many points scoring leader offensive force'")
    print("=" * 70)

    conn = get_connection('gold')
    model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')

    query = "elite superstar many points scoring leader offensive force"
    query_embedding = model.encode(query)
    vec_array = array.array('f', query_embedding)

    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            full_name,
            position_code,
            season,
            points,
            goals,
            assists,
            ROUND(VECTOR_DISTANCE(narrative_vector, :vec, COSINE), 4) AS similarity
        FROM gold_player_season_stats
        WHERE narrative_vector IS NOT NULL
        ORDER BY VECTOR_DISTANCE(narrative_vector, :vec, COSINE)
        FETCH FIRST 10 ROWS ONLY
    """, {'vec': vec_array})

    results = cursor.fetchall()

    elite = sum(1 for r in results if r[3] >= 50)
    avg_pts = sum(r[3] for r in results) / len(results)
    avg_sim = sum(r[6] for r in results) / len(results)

    print(f"\nTop 10 Results:")
    for i, (name, pos, season, pts, g, a, sim) in enumerate(results, 1):
        season_str = f"{str(season)[:4]}-{str(season)[4:6]}"
        print(f"{i}. {name} ({pos}) — {season_str}: {pts}pts ({g}G {a}A)")
        print(f"   Similarity: {sim}")

    print(f"\nMetrics:")
    print(f"  Elite players (≥50 pts): {elite}/10 ({elite*10}%)")
    print(f"  Average points: {avg_pts:.1f}")
    print(f"  Average similarity: {avg_sim:.4f}")

    cursor.close()
    conn.close()

    return elite, avg_pts


def main():
    print("=" * 70)
    print("ENHANCED NARRATIVE VALIDATION SUITE")
    print("Testing improvements from richer context")
    print("=" * 70)

    # Run all tests
    blowout_precision, blowout_diff = test_blowout_detection()
    defensive_precision, defensive_goals = test_defensive_battle()
    shootout_precision, shootout_goals = test_high_scoring()
    elite_precision, elite_pts = test_elite_players()

    # Summary
    print("\n" + "=" * 70)
    print("IMPROVEMENT SUMMARY")
    print("=" * 70)

    print(f"""
✅ Blowout Detection:
   Precision: {blowout_precision}/10 ({blowout_precision*10}%)
   Avg Goal Diff: {blowout_diff:.1f}
   Target: 60%+ blowouts (4+ goal margin)
   Status: {'✓ PASS' if blowout_precision >= 6 else '⚠ NEEDS WORK'}

✅ Defensive Battle Detection:
   Precision: {defensive_precision}/10 ({defensive_precision*10}%)
   Avg Total Goals: {defensive_goals:.1f}
   Target: 70%+ low-scoring (≤3 goals)
   Status: {'✓ PASS' if defensive_precision >= 7 else '⚠ NEEDS WORK'}

✅ Offensive Shootout Detection:
   Precision: {shootout_precision}/10 ({shootout_precision*10}%)
   Avg Total Goals: {shootout_goals:.1f}
   Target: 60%+ high-scoring (≥7 goals)
   Status: {'✓ PASS' if shootout_precision >= 6 else '⚠ NEEDS WORK'}

✅ Elite Player Detection:
   Precision: {elite_precision}/10 ({elite_precision*10}%)
   Avg Points: {elite_pts:.1f}
   Target: 60%+ elite players (≥50 pts)
   Status: {'✓ PASS' if elite_precision >= 6 else '⚠ NEEDS WORK'}
""")

    overall = (blowout_precision + defensive_precision + shootout_precision + elite_precision) / 4
    print(f"\n{'=' * 70}")
    print(f"Overall Precision: {overall*10:.0f}%")
    print(f"{'=' * 70}")

if __name__ == "__main__":
    main()
