#!/usr/bin/env python3
"""
Hybrid Search - Combines Oracle VECTOR semantic search with SQL filters
Demonstrates the power of native Oracle AI + traditional database capabilities
"""

import oracledb
from config.db_connect import get_connection
from sentence_transformers import SentenceTransformer
import array
from typing import List, Optional, Dict, Any
from datetime import datetime

class HybridSearchEngine:
    """Combines semantic vector search with traditional SQL filters"""

    def __init__(self):
        self.model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
        self.conn = None

    def connect(self):
        """Establish database connection"""
        if not self.conn:
            self.conn = get_connection('gold')

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None

    def search_games(
        self,
        query: str,
        teams: Optional[List[str]] = None,
        min_total_goals: Optional[int] = None,
        max_total_goals: Optional[int] = None,
        min_goal_diff: Optional[int] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        overtime_only: bool = False,
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search for games combining semantic similarity with filters

        Args:
            query: Natural language search query
            teams: List of team abbreviations to filter by
            min_total_goals: Minimum total goals in game
            max_total_goals: Maximum total goals in game
            min_goal_diff: Minimum goal differential
            date_from: Start date (YYYY-MM-DD)
            date_to: End date (YYYY-MM-DD)
            overtime_only: Only return overtime/shootout games
            top_k: Number of results to return

        Returns:
            List of game results with metadata
        """
        self.connect()

        # Generate embedding
        query_embedding = self.model.encode(query)
        vec_array = array.array('f', query_embedding)

        # Build dynamic WHERE clause
        where_conditions = []
        params = {'vec': vec_array, 'k': top_k}

        if teams:
            team_placeholders = ','.join([f':team{i}' for i in range(len(teams))])
            where_conditions.append(f"(home_team_name IN ({team_placeholders}) OR away_team_name IN ({team_placeholders}))")
            for i, team in enumerate(teams):
                params[f'team{i}'] = team

        if min_total_goals is not None:
            where_conditions.append("(home_score + away_score) >= :min_goals")
            params['min_goals'] = min_total_goals

        if max_total_goals is not None:
            where_conditions.append("(home_score + away_score) <= :max_goals")
            params['max_goals'] = max_total_goals

        if min_goal_diff is not None:
            where_conditions.append("ABS(home_score - away_score) >= :min_diff")
            params['min_diff'] = min_goal_diff

        if date_from:
            where_conditions.append("game_date >= TO_DATE(:date_from, 'YYYY-MM-DD')")
            params['date_from'] = date_from

        if date_to:
            where_conditions.append("game_date <= TO_DATE(:date_to, 'YYYY-MM-DD')")
            params['date_to'] = date_to

        if overtime_only:
            where_conditions.append("(overtime_flag = 'Y' OR shootout_flag = 'Y')")

        # Add base condition
        where_conditions.append("narrative_vector IS NOT NULL")

        # Build SQL
        where_clause = " AND ".join(where_conditions)

        sql = f"""
            SELECT
                game_id,
                game_date,
                home_team_name,
                away_team_name,
                home_score,
                away_score,
                CASE
                    WHEN shootout_flag = 'Y' THEN 'SO'
                    WHEN overtime_flag = 'Y' THEN 'OT'
                    ELSE 'REG'
                END AS period_type,
                ROUND(VECTOR_DISTANCE(narrative_vector, :vec, COSINE), 4) AS similarity,
                narrative_text
            FROM gold_game_narratives
            WHERE {where_clause}
            ORDER BY VECTOR_DISTANCE(narrative_vector, :vec, COSINE)
            FETCH FIRST :k ROWS ONLY
        """

        cursor = self.conn.cursor()
        cursor.execute(sql, params)

        results = []
        for row in cursor.fetchall():
            results.append({
                'game_id': row[0],
                'game_date': row[1],
                'home_team': row[2],
                'away_team': row[3],
                'home_score': row[4],
                'away_score': row[5],
                'period_type': row[6],
                'similarity': row[7],
                'narrative': row[8]
            })

        cursor.close()
        return results

    def search_players(
        self,
        query: str,
        positions: Optional[List[str]] = None,
        min_points: Optional[int] = None,
        max_points: Optional[int] = None,
        min_games: Optional[int] = None,
        seasons: Optional[List[int]] = None,
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Hybrid search for players combining semantic similarity with filters

        Args:
            query: Natural language search query
            positions: List of positions (C, L, R, D, G)
            min_points: Minimum points
            max_points: Maximum points
            min_games: Minimum games played
            seasons: List of seasons (e.g., [20202021, 20212022])
            top_k: Number of results to return

        Returns:
            List of player results with metadata
        """
        self.connect()

        # Generate embedding
        query_embedding = self.model.encode(query)
        vec_array = array.array('f', query_embedding)

        # Build dynamic WHERE clause
        where_conditions = []
        params = {'vec': vec_array, 'k': top_k}

        if positions:
            pos_placeholders = ','.join([f':pos{i}' for i in range(len(positions))])
            where_conditions.append(f"position_code IN ({pos_placeholders})")
            for i, pos in enumerate(positions):
                params[f'pos{i}'] = pos

        if min_points is not None:
            where_conditions.append("points >= :min_pts")
            params['min_pts'] = min_points

        if max_points is not None:
            where_conditions.append("points <= :max_pts")
            params['max_pts'] = max_points

        if min_games is not None:
            where_conditions.append("games_played >= :min_games")
            params['min_games'] = min_games

        if seasons:
            season_placeholders = ','.join([f':season{i}' for i in range(len(seasons))])
            where_conditions.append(f"season IN ({season_placeholders})")
            for i, season in enumerate(seasons):
                params[f'season{i}'] = season

        # Add base condition
        where_conditions.append("narrative_vector IS NOT NULL")

        # Build SQL
        where_clause = " AND ".join(where_conditions)

        sql = f"""
            SELECT
                player_id,
                full_name,
                season,
                position_code,
                games_played,
                goals,
                assists,
                points,
                plus_minus,
                ROUND(VECTOR_DISTANCE(narrative_vector, :vec, COSINE), 4) AS similarity,
                narrative_text
            FROM gold_player_season_stats
            WHERE {where_clause}
            ORDER BY VECTOR_DISTANCE(narrative_vector, :vec, COSINE)
            FETCH FIRST :k ROWS ONLY
        """

        cursor = self.conn.cursor()
        cursor.execute(sql, params)

        results = []
        for row in cursor.fetchall():
            season_str = f"{str(row[2])[:4]}-{str(row[2])[4:6]}"
            results.append({
                'player_id': row[0],
                'name': row[1],
                'season': season_str,
                'position': row[3],
                'games_played': row[4],
                'goals': row[5],
                'assists': row[6],
                'points': row[7],
                'plus_minus': row[8],
                'similarity': row[9],
                'narrative': row[10]
            })

        cursor.close()
        return results

    def find_similar_players(
        self,
        player_name: str,
        same_position_only: bool = True,
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Find players with similar playing styles using average vector similarity

        Args:
            player_name: Name of reference player
            same_position_only: Only return players in same position
            top_k: Number of similar players to return

        Returns:
            List of similar players
        """
        self.connect()
        cursor = self.conn.cursor()

        # Get reference player's average vector and position
        cursor.execute("""
            SELECT VECTOR(AVG(narrative_vector), 384, FLOAT32) as avg_vec, MAX(position_code) as pos
            FROM gold_player_season_stats
            WHERE full_name LIKE :name
              AND narrative_vector IS NOT NULL
        """, {'name': f'%{player_name}%'})

        result = cursor.fetchone()
        if not result or not result[0]:
            cursor.close()
            return []

        ref_vector = result[0]
        ref_position = result[1]

        # Find similar players
        params = {'ref_vec': ref_vector, 'k': top_k, 'ref_name': f'%{player_name}%'}
        position_filter = "AND p.position_code = :ref_pos" if same_position_only else ""
        if same_position_only:
            params['ref_pos'] = ref_position

        sql = f"""
            SELECT
                p.full_name,
                p.position_code,
                COUNT(DISTINCT p.season) as seasons,
                ROUND(AVG(p.points), 1) as avg_points,
                ROUND(AVG(VECTOR_DISTANCE(p.narrative_vector, :ref_vec, COSINE)), 4) as avg_similarity
            FROM gold_player_season_stats p
            WHERE p.narrative_vector IS NOT NULL
              AND p.full_name NOT LIKE :ref_name
              {position_filter}
            GROUP BY p.full_name, p.position_code
            ORDER BY avg_similarity
            FETCH FIRST :k ROWS ONLY
        """

        cursor.execute(sql, params)

        results = []
        for row in cursor.fetchall():
            results.append({
                'name': row[0],
                'position': row[1],
                'seasons': row[2],
                'avg_points': row[3],
                'similarity': row[4]
            })

        cursor.close()
        return results


def demo():
    """Demonstrate hybrid search capabilities"""
    engine = HybridSearchEngine()

    print("=" * 70)
    print("HYBRID SEARCH DEMONSTRATION")
    print("Combining Oracle VECTOR search with SQL filters")
    print("=" * 70)

    # Example 1: Semantic search + team filter
    print("\n1. HIGH-SCORING COLORADO AVALANCHE GAMES")
    print("Query: 'offensive high scoring'")
    print("Filters: teams=['Colorado Avalanche'], min_total_goals=7")
    print("-" * 70)

    results = engine.search_games(
        query="offensive high scoring",
        teams=["Colorado Avalanche"],
        min_total_goals=7,
        top_k=5
    )

    for i, game in enumerate(results, 1):
        total = game['home_score'] + game['away_score']
        print(f"{i}. {game['away_team']} @ {game['home_team']}: {game['away_score']}-{game['home_score']}")
        print(f"   Date: {game['game_date'].strftime('%Y-%m-%d')} | Total: {total} | Similarity: {game['similarity']}")

    # Example 2: Semantic search + goal differential filter
    print("\n\n2. DOMINANT BLOWOUT VICTORIES")
    print("Query: 'blowout dominant victory'")
    print("Filters: min_goal_diff=5")
    print("-" * 70)

    results = engine.search_games(
        query="blowout dominant victory",
        min_goal_diff=5,
        top_k=5
    )

    for i, game in enumerate(results, 1):
        diff = abs(game['home_score'] - game['away_score'])
        winner = game['home_team'] if game['home_score'] > game['away_score'] else game['away_team']
        print(f"{i}. {game['away_team']} @ {game['home_team']}: {game['away_score']}-{game['home_score']}")
        print(f"   Winner: {winner} | Goal Diff: {diff} | Similarity: {game['similarity']}")

    # Example 3: Overtime games only
    print("\n\n3. DRAMATIC OVERTIME GAMES")
    print("Query: 'dramatic thriller close'")
    print("Filters: overtime_only=True")
    print("-" * 70)

    results = engine.search_games(
        query="dramatic thriller close",
        overtime_only=True,
        top_k=5
    )

    for i, game in enumerate(results, 1):
        print(f"{i}. {game['away_team']} @ {game['home_team']}: {game['away_score']}-{game['home_score']} ({game['period_type']})")
        print(f"   Similarity: {game['similarity']}")

    # Example 4: Player search with filters
    print("\n\n4. ELITE CENTERS WITH 40+ POINTS")
    print("Query: 'elite scorer offensive force'")
    print("Filters: positions=['C'], min_points=40")
    print("-" * 70)

    results = engine.search_players(
        query="elite scorer offensive force",
        positions=['C'],
        min_points=40,
        top_k=5
    )

    for i, player in enumerate(results, 1):
        print(f"{i}. {player['name']} ({player['position']}) — {player['season']}")
        print(f"   {player['points']}pts ({player['goals']}G {player['assists']}A) | Similarity: {player['similarity']}")

    # Example 5: Find players similar to McDavid
    print("\n\n5. PLAYERS SIMILAR TO C. MCDAVID")
    print("Using multi-season vector averaging")
    print("-" * 70)

    results = engine.find_similar_players(
        player_name="McDavid",
        same_position_only=True,
        top_k=5
    )

    for i, player in enumerate(results, 1):
        print(f"{i}. {player['name']} ({player['position']})")
        print(f"   {player['seasons']} seasons | Avg {player['avg_points']} pts/season | Similarity: {player['similarity']}")

    engine.close()

    print("\n" + "=" * 70)
    print("Hybrid search combines the best of both worlds:")
    print("  ✓ Semantic understanding (VECTOR search)")
    print("  ✓ Precise filtering (SQL WHERE clauses)")
    print("  ✓ Native Oracle performance (<10ms queries)")
    print("=" * 70)


if __name__ == "__main__":
    demo()
