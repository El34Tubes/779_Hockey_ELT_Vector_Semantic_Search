"""
Generate Vector Embeddings using Sentence Transformers
=======================================================
Reads narrative text from gold tables and generates 384-dimensional
vector embeddings using the all-MiniLM-L6-v2 model.

Embeddings are written to Oracle VECTOR columns for semantic search.

Prerequisites:
  pip install sentence-transformers

Usage:
  python etl/generate_embeddings.py                    # all tables
  python etl/generate_embeddings.py --table games      # games only
  python etl/generate_embeddings.py --batch-size 100   # custom batch size
"""

import sys, os, argparse
from datetime import datetime
import numpy as np
import array

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.db_connect import get_connection

# Check for sentence-transformers
try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    print("ERROR: sentence-transformers not installed")
    print("Install with: pip install sentence-transformers")
    sys.exit(1)


def load_model():
    """Load the sentence-transformers embedding model."""
    print("Loading sentence-transformers model (all-MiniLM-L6-v2)...")
    model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    print(f"✓ Model loaded (embedding dim: {model.get_sentence_embedding_dimension()})")
    return model


def embed_game_narratives(conn, model, batch_size=100):
    """Generate embeddings for game narratives."""
    cursor = conn.cursor()

    # Fetch games needing embeddings
    cursor.execute("""
        SELECT game_id, narrative_text
        FROM gold_game_narratives
        WHERE narrative_vector IS NULL
          AND narrative_text IS NOT NULL
        ORDER BY game_id
    """)

    rows = cursor.fetchall()
    if not rows:
        print("  No games need embeddings")
        return 0

    print(f"  Generating embeddings for {len(rows)} games...")

    game_ids = [r[0] for r in rows]
    texts = [r[1] for r in rows]

    # Generate embeddings in batches
    update_cursor = conn.cursor()
    total_embedded = 0

    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i:i+batch_size]
        batch_ids = game_ids[i:i+batch_size]

        # Generate embeddings
        embeddings = model.encode(batch_texts, show_progress_bar=False)

        # Write to Oracle (convert numpy array to array.array for VECTOR binding)
        for game_id, embedding in zip(batch_ids, embeddings):
            vec_array = array.array('f', embedding)  # numpy → float32 array

            update_cursor.execute(
                "UPDATE gold_game_narratives SET narrative_vector = :1 WHERE game_id = :2",
                (vec_array, game_id)
            )

        conn.commit()
        total_embedded += len(batch_ids)

        if (i + batch_size) % 500 == 0 or total_embedded == len(texts):
            print(f"    {total_embedded}/{len(texts)} games embedded...")

    cursor.close()
    update_cursor.close()

    return total_embedded


def embed_player_stats(conn, model, batch_size=100):
    """Generate embeddings for player season stats."""
    cursor = conn.cursor()

    cursor.execute("""
        SELECT player_id, season, narrative_text
        FROM gold_player_season_stats
        WHERE narrative_vector IS NULL
          AND narrative_text IS NOT NULL
        ORDER BY player_id, season
    """)

    rows = cursor.fetchall()
    if not rows:
        print("  No player-seasons need embeddings")
        return 0

    print(f"  Generating embeddings for {len(rows)} player-seasons...")

    player_ids = [r[0] for r in rows]
    seasons = [r[1] for r in rows]
    texts = [r[2] for r in rows]

    update_cursor = conn.cursor()
    total_embedded = 0

    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i:i+batch_size]
        batch_player_ids = player_ids[i:i+batch_size]
        batch_seasons = seasons[i:i+batch_size]

        embeddings = model.encode(batch_texts, show_progress_bar=False)

        for player_id, season, embedding in zip(batch_player_ids, batch_seasons, embeddings):
            vec_array = array.array('f', embedding)

            update_cursor.execute(
                "UPDATE gold_player_season_stats SET narrative_vector = :1 WHERE player_id = :2 AND season = :3",
                (vec_array, player_id, season)
            )

        conn.commit()
        total_embedded += len(batch_player_ids)

        if (i + batch_size) % 500 == 0 or total_embedded == len(texts):
            print(f"    {total_embedded}/{len(texts)} player-seasons embedded...")

    cursor.close()
    update_cursor.close()

    return total_embedded


def embed_team_summaries(conn, model, batch_size=100):
    """Generate embeddings for team season summaries."""
    cursor = conn.cursor()

    cursor.execute("""
        SELECT team_abbrev, season, narrative_text
        FROM gold_team_season_summary
        WHERE narrative_vector IS NULL
          AND narrative_text IS NOT NULL
        ORDER BY team_abbrev, season
    """)

    rows = cursor.fetchall()
    if not rows:
        print("  No team-seasons need embeddings")
        return 0

    print(f"  Generating embeddings for {len(rows)} team-seasons...")

    team_abbrevs = [r[0] for r in rows]
    seasons = [r[1] for r in rows]
    texts = [r[2] for r in rows]

    embeddings = model.encode(texts, show_progress_bar=False)

    update_cursor = conn.cursor()
    for team_abbrev, season, embedding in zip(team_abbrevs, seasons, embeddings):
        vec_array = array.array('f', embedding)

        update_cursor.execute(
            "UPDATE gold_team_season_summary SET narrative_vector = :1 WHERE team_abbrev = :2 AND season = :3",
            (vec_array, team_abbrev, season)
        )

    conn.commit()
    cursor.close()
    update_cursor.close()

    return len(rows)


def main():
    parser = argparse.ArgumentParser(description="Generate vector embeddings for semantic search")
    parser.add_argument("--table", choices=["games", "players", "teams", "all"], default="all",
                        help="Which table(s) to process")
    parser.add_argument("--batch-size", type=int, default=100,
                        help="Batch size for embedding generation (default: 100)")
    args = parser.parse_args()

    print("="*70)
    print("VECTOR EMBEDDING GENERATION")
    print(f"Started: {datetime.now().isoformat()}")
    print("="*70)

    # Load model
    model = load_model()

    # Connect to database
    conn = get_connection("gold")

    total_count = 0

    try:
        if args.table in ["games", "all"]:
            print("\n[1/3] Game Narratives:")
            count = embed_game_narratives(conn, model, args.batch_size)
            print(f"  ✓ Embedded {count} games")
            total_count += count

        if args.table in ["players", "all"]:
            print("\n[2/3] Player Season Stats:")
            count = embed_player_stats(conn, model, args.batch_size)
            print(f"  ✓ Embedded {count} player-seasons")
            total_count += count

        if args.table in ["teams", "all"]:
            print("\n[3/3] Team Season Summaries:")
            count = embed_team_summaries(conn, model, args.batch_size)
            print(f"  ✓ Embedded {count} team-seasons")
            total_count += count

    finally:
        conn.close()

    print("\n" + "="*70)
    print(f"TOTAL: {total_count} embeddings generated")
    print(f"Finished: {datetime.now().isoformat()}")
    print("="*70)

    print("\nNext steps:")
    print("  1. Create vector indexes: sql/create_vector_indexes.sql")
    print("  2. Test semantic search: python exploration/semantic_search_demo.py")


if __name__ == "__main__":
    main()
