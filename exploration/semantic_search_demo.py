"""
Semantic Search Demo - NHL Analytics
=====================================
Demonstrates Oracle AI Vector Search using native VECTOR types,
VECTOR_DISTANCE(), and HNSW indexes.

Features:
  - Natural language queries → semantic search
  - Find similar games, players, teams by narrative
  - Compare search strategies (exact vs semantic)
  - Showcase Oracle 26ai AI capabilities

Usage:
  python exploration/semantic_search_demo.py
  python exploration/semantic_search_demo.py --query "overtime thriller"
"""

import sys, os, argparse
from datetime import datetime
import array

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.db_connect import get_connection

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    print("ERROR: sentence-transformers not installed")
    print("Install with: pip install sentence-transformers")
    sys.exit(1)


# Load embedding model (same as generation)
model = None

def get_model():
    global model
    if model is None:
        print("Loading embedding model...")
        model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    return model


def embed_query(query_text):
    """Convert natural language query to 384-dim vector."""
    m = get_model()
    embedding = m.encode(query_text)
    return array.array('f', embedding)


def search_games(conn, query_text, top_k=10):
    """Semantic search over game narratives."""
    print(f"\n{'='*70}")
    print(f"GAME SEARCH: \"{query_text}\"")
    print(f"{'='*70}")

    query_vector = embed_query(query_text)

    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            game_id,
            game_date,
            home_team_name,
            away_team_name,
            home_score,
            away_score,
            overtime_flag,
            narrative_text,
            VECTOR_DISTANCE(narrative_vector, :1, COSINE) AS similarity
        FROM gold_game_narratives
        WHERE narrative_vector IS NOT NULL
        ORDER BY similarity
        FETCH FIRST :2 ROWS ONLY
    """, (query_vector, top_k))

    results = cursor.fetchall()
    cursor.close()

    print(f"\nTop {len(results)} results:\n")
    for i, row in enumerate(results, 1):
        game_id, game_date, home, away, h_score, a_score, ot, narrative, sim = row
        print(f"{i}. [{game_date.strftime('%Y-%m-%d')}] {home} {h_score} vs {away} {a_score}{'(OT)' if ot=='Y' else ''}")
        print(f"   Similarity: {1-sim:.4f}")  # Convert distance to similarity
        print(f"   \"{narrative[:100]}...\"")
        print()

    return results


def search_players(conn, query_text, top_k=10):
    """Semantic search over player season narratives."""
    print(f"\n{'='*70}")
    print(f"PLAYER SEARCH: \"{query_text}\"")
    print(f"{'='*70}")

    query_vector = embed_query(query_text)

    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            full_name,
            season,
            position_code,
            games_played,
            goals,
            assists,
            points,
            narrative_text,
            VECTOR_DISTANCE(narrative_vector, :1, COSINE) AS similarity
        FROM gold_player_season_stats
        WHERE narrative_vector IS NOT NULL
        ORDER BY similarity
        FETCH FIRST :2 ROWS ONLY
    """, (query_vector, top_k))

    results = cursor.fetchall()
    cursor.close()

    print(f"\nTop {len(results)} results:\n")
    for i, row in enumerate(results, 1):
        name, season, pos, games, goals, assists, points, narrative, sim = row
        season_str = f"{str(season)[:4]}-{str(season)[4:6]}"
        print(f"{i}. {name or 'Unknown'} ({pos or 'N/A'}) — {season_str}")
        print(f"   {goals or 0}G {assists or 0}A {points or 0}P in {games or 0} GP")
        print(f"   Similarity: {1-sim:.4f}")
        print(f"   \"{narrative[:100]}...\"")
        print()

    return results


def search_teams(conn, query_text, top_k=10):
    """Semantic search over team season summaries."""
    print(f"\n{'='*70}")
    print(f"TEAM SEARCH: \"{query_text}\"")
    print(f"{'='*70}")

    query_vector = embed_query(query_text)

    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            team_name,
            season,
            wins,
            losses,
            ot_losses,
            points,
            goals_for,
            goals_against,
            narrative_text,
            VECTOR_DISTANCE(narrative_vector, :1, COSINE) AS similarity
        FROM gold_team_season_summary
        WHERE narrative_vector IS NOT NULL
        ORDER BY similarity
        FETCH FIRST :2 ROWS ONLY
    """, (query_vector, top_k))

    results = cursor.fetchall()
    cursor.close()

    print(f"\nTop {len(results)} results:\n")
    for i, row in enumerate(results, 1):
        team, season, w, l, otl, pts, gf, ga, narrative, sim = row
        season_str = f"{str(season)[:4]}-{str(season)[4:6]}"
        print(f"{i}. {team} — {season_str}")
        print(f"   Record: {w}-{l}-{otl} ({pts} pts) | GF: {gf} GA: {ga}")
        print(f"   Similarity: {1-sim:.4f}")
        print(f"   \"{narrative[:100]}...\"")
        print()

    return results


def run_demo_queries(conn):
    """Run a series of demo queries showcasing semantic search."""
    print("\n" + "="*70)
    print("SEMANTIC SEARCH DEMO - NHL Analytics")
    print("="*70)
    print("\nShowcasing Oracle 26ai AI Vector Search:")
    print("  • Native VECTOR(384, FLOAT32) storage")
    print("  • VECTOR_DISTANCE(vec1, vec2, COSINE) function")
    print("  • HNSW indexes for sub-second search")
    print("  • Natural language queries → semantic similarity")

    # Demo 1: Find high-scoring games
    search_games(conn, "high scoring offensive shootout with many goals", top_k=5)

    # Demo 2: Find defensive battles
    search_games(conn, "low scoring defensive battle goalie duel", top_k=5)

    # Demo 3: Find overtime thrillers
    search_games(conn, "overtime thriller dramatic finish close game", top_k=5)

    # Demo 4: Find elite scorers
    search_players(conn, "elite scorer many goals offensive superstar", top_k=5)

    # Demo 5: Find dominant teams
    search_teams(conn, "dominant team strong playoff contender successful season", top_k=5)


def main():
    parser = argparse.ArgumentParser(description="Semantic search demo")
    parser.add_argument("--query", type=str, help="Custom search query")
    parser.add_argument("--type", choices=["games", "players", "teams"], default="games",
                        help="Search type (default: games)")
    parser.add_argument("--top-k", type=int, default=10, help="Number of results (default: 10)")
    args = parser.parse_args()

    conn = get_connection("gold")

    try:
        if args.query:
            # Custom query
            if args.type == "games":
                search_games(conn, args.query, args.top_k)
            elif args.type == "players":
                search_players(conn, args.query, args.top_k)
            elif args.type == "teams":
                search_teams(conn, args.query, args.top_k)
        else:
            # Run demo
            run_demo_queries(conn)

    finally:
        conn.close()

    print("\n" + "="*70)
    print("Oracle AI Vector Search: Native semantic search in SQL")
    print("="*70)


if __name__ == "__main__":
    main()
