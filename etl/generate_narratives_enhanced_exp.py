#!/usr/bin/env python3
"""
Enhanced Narrative Text Generation with Rich Context
Generates descriptive narratives using period-by-period data, goal differential, game flow, etc.
"""

import oracledb
from config.db_connect import get_connection
from datetime import datetime

def generate_enhanced_game_narrative(conn, game_id):
    """Generate rich narrative for a single game using period-by-period data."""
    cursor = conn.cursor()

    # Get game metadata
    cursor.execute("""
        SELECT game_date, home_team, away_team, home_score, away_score,
               last_period_type, home_sog, away_sog, venue
        FROM silver_schema.silver_games
        WHERE game_id = :gid
    """, {'gid': game_id})

    game_row = cursor.fetchone()
    if not game_row:
        return None

    game_date, home_team, away_team, home_score, away_score, period_type, home_sog, away_sog, venue = game_row

    # Get period-by-period scoring
    cursor.execute("""
        SELECT period, COUNT(*) as goals,
               SUM(CASE WHEN team_abbrev = :home THEN 1 ELSE 0 END) as home_goals,
               SUM(CASE WHEN team_abbrev = :away THEN 1 ELSE 0 END) as away_goals,
               SUM(CASE WHEN strength = 'pp' THEN 1 ELSE 0 END) as pp_goals,
               MAX(CASE WHEN SUBSTR(time_in_period, 1, 2) >= '15' THEN 1 ELSE 0 END) as late_period_goal
        FROM silver_schema.silver_goals
        WHERE game_id = :gid
        GROUP BY period
        ORDER BY period
    """, {'gid': game_id, 'home': home_team, 'away': away_team})

    period_scoring = cursor.fetchall()

    # Calculate game characteristics
    total_goals = home_score + away_score
    goal_diff = abs(home_score - away_score)
    winner = home_team if home_score > away_score else away_team
    loser = away_team if home_score > away_score else home_team

    # Build narrative with rich context
    narrative_parts = []

    # Opening with date and matchup
    date_str = game_date.strftime('%B %d, %Y')
    narrative_parts.append(f"On {date_str}, the {away_team} visited the {home_team}")
    if venue:
        narrative_parts.append(f" at {venue}")
    narrative_parts.append(".")

    # Game flow description
    if goal_diff >= 4:
        # Blowout
        narrative_parts.append(f" In a dominant one-sided performance, the {winner} cruised to a decisive {home_score}-{away_score} blowout victory over the {loser}.")
    elif goal_diff == 0:
        # Tie (shouldn't happen but handle it)
        narrative_parts.append(f" The teams battled to a {home_score}-{away_score} stalemate.")
    elif goal_diff == 1:
        # Close game
        narrative_parts.append(f" In a tightly-contested battle, the {winner} edged the {loser} by a narrow {home_score}-{away_score} margin.")
    elif goal_diff <= 2:
        # Competitive game
        narrative_parts.append(f" The {winner} emerged victorious {home_score}-{away_score} in a competitive matchup against the {loser}.")
    else:
        # Standard win
        narrative_parts.append(f" The {winner} defeated the {loser} {home_score}-{away_score}.")

    # Scoring pace description
    if total_goals >= 8:
        narrative_parts.append(f" This offensive shootout featured {total_goals} total goals in a high-scoring affair.")
    elif total_goals <= 3:
        narrative_parts.append(f" Both goaltenders were stellar in this defensive battle with just {total_goals} total goals.")
    elif total_goals >= 6:
        narrative_parts.append(f" The teams combined for {total_goals} goals in a back-and-forth offensive contest.")

    # Period-by-period flow (detect comebacks, etc.)
    if len(period_scoring) >= 3:
        p1_home, p1_away = 0, 0
        p2_home, p2_away = 0, 0
        p3_home, p3_away = 0, 0

        for period, _, home_g, away_g, pp_g, late in period_scoring:
            if period == 1:
                p1_home, p1_away = home_g, away_g
            elif period == 2:
                p2_home, p2_away = home_g, away_g
            elif period == 3:
                p3_home, p3_away = home_g, away_g

        # Detect comeback
        p2_total_home = p1_home + p2_home
        p2_total_away = p1_away + p2_away

        if home_score > away_score and p2_total_away > p2_total_home:
            narrative_parts.append(f" The {home_team} mounted a dramatic comeback, trailing after two periods before rallying in the third.")
        elif away_score > home_score and p2_total_home > p2_total_away:
            narrative_parts.append(f" The {away_team} staged a thrilling rally, overcoming a deficit to claim victory.")

        # Late drama
        has_late_goal = any(late for _, _, _, _, _, late in period_scoring if late)
        if has_late_goal and goal_diff <= 1:
            narrative_parts.append(" Late-period goals added to the drama in this nail-biter.")

    # Overtime/Shootout
    if period_type == 'OT':
        narrative_parts.append(" The game required overtime to decide the winner, adding extra excitement to the contest.")
    elif period_type == 'SO':
        narrative_parts.append(" After a scoreless overtime, the game was decided in a dramatic shootout.")

    # Special teams (if we have PP goals)
    total_pp_goals = sum(pp_g for _, _, _, _, pp_g, _ in period_scoring)
    if total_pp_goals >= 3:
        narrative_parts.append(f" Special teams played a crucial role with {total_pp_goals} power-play goals.")

    # Shot totals
    if home_sog and away_sog:
        shot_diff = abs(home_sog - away_sog)
        if shot_diff >= 15:
            shot_leader = home_team if home_sog > away_sog else away_team
            narrative_parts.append(f" The {shot_leader} dominated possession and outshot their opponent significantly.")

    cursor.close()
    return ''.join(narrative_parts)


def generate_enhanced_player_narrative(row):
    """Generate rich narrative for player season with comparisons and context."""
    player_id, season, full_name, position, games, goals, assists, pts, pm, pim, sog = row

    name = full_name or f"Player {player_id}"
    season_str = f"{str(season)[:4]}-{str(season)[4:6]}"
    pos_name = {
        'C': 'center', 'L': 'left wing', 'R': 'right wing',
        'D': 'defenseman', 'G': 'goaltender'
    }.get(position, position)

    narrative_parts = []

    # Opening
    narrative_parts.append(f"{name}, a {pos_name}, ")

    # Production level assessment
    if pts >= 60:
        narrative_parts.append(f"had an elite {season_str} season")
    elif pts >= 40:
        narrative_parts.append(f"enjoyed a strong {season_str} campaign")
    elif pts >= 20:
        narrative_parts.append(f"contributed solidly during the {season_str} season")
    else:
        narrative_parts.append(f"played {games or 0} games in the {season_str} season")

    # Goal/assist breakdown
    if goals and assists:
        if goals > assists * 2:
            narrative_parts.append(f", demonstrating scoring prowess with {goals} goals (goal-first mentality)")
        elif assists > goals * 2:
            narrative_parts.append(f", showcasing playmaking ability with {assists} assists (pass-first approach)")
        else:
            narrative_parts.append(f", recording a balanced {goals} goals and {assists} assists")
        narrative_parts.append(f" for {pts} total points")

    # Games played context
    if games:
        narrative_parts.append(f" over {games} games")
        if games >= 70:
            narrative_parts.append(" (durable workhorse)")
        elif games <= 20:
            narrative_parts.append(" (limited action)")

    # Plus/minus assessment
    if pm is not None:
        if pm >= 15:
            narrative_parts.append(f". Defensively responsible with a stellar +{pm} rating")
        elif pm <= -15:
            narrative_parts.append(f". Struggled defensively with a {pm:+d} rating")
        elif abs(pm) >= 5:
            narrative_parts.append(f", posting a {pm:+d} plus/minus")

    # Physical play
    if pim is not None and pim >= 50:
        narrative_parts.append(f". Known for physical, gritty play with {pim} penalty minutes")

    # Shooting
    if sog and goals and sog > 0:
        shot_pct = (goals / sog) * 100
        if shot_pct >= 15:
            narrative_parts.append(f". Elite shooting accuracy at {shot_pct:.1f}% (pure sniper)")
        elif shot_pct >= 10:
            narrative_parts.append(f". Good shooting touch at {shot_pct:.1f}%")

    narrative_parts.append(".")

    return ''.join(narrative_parts)


def main():
    print("=" * 70)
    print("ENHANCED NARRATIVE GENERATION")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 70)

    conn = get_connection('gold')
    cursor = conn.cursor()

    # 1. Generate enhanced game narratives
    cursor.execute("""
        SELECT game_id
        FROM gold_game_narratives
        WHERE narrative_text IS NULL OR LENGTH(narrative_text) < 200
        ORDER BY game_id
    """)

    game_ids = [row[0] for row in cursor.fetchall()]
    print(f"\nGenerating enhanced narratives for {len(game_ids)} games...")

    update_cursor = conn.cursor()
    for i, game_id in enumerate(game_ids, 1):
        narrative = generate_enhanced_game_narrative(conn, game_id)
        if narrative:
            update_cursor.execute("""
                UPDATE gold_game_narratives
                SET narrative_text = :narrative, updated_at = SYSTIMESTAMP
                WHERE game_id = :gid
            """, {'narrative': narrative, 'gid': game_id})

        if i % 500 == 0:
            print(f"  {i}/{len(game_ids)} games processed...")
            conn.commit()

    conn.commit()
    print(f"✓ Generated enhanced narratives for {len(game_ids)} games")

    # 2. Generate enhanced player narratives
    cursor.execute("""
        SELECT player_id, season, full_name, position_code,
               games_played, goals, assists, points, plus_minus, pim, shots
        FROM gold_player_season_stats
        WHERE narrative_text IS NULL OR LENGTH(narrative_text) < 100
        ORDER BY player_id, season
    """)

    player_rows = cursor.fetchall()
    print(f"\nGenerating enhanced narratives for {len(player_rows)} player-seasons...")

    for i, row in enumerate(player_rows, 1):
        narrative = generate_enhanced_player_narrative(row)
        update_cursor.execute("""
            UPDATE gold_player_season_stats
            SET narrative_text = :narrative, updated_at = SYSTIMESTAMP
            WHERE player_id = :pid AND season = :season
        """, {'narrative': narrative, 'pid': row[0], 'season': row[1]})

        if i % 500 == 0:
            print(f"  {i}/{len(player_rows)} player-seasons processed...")
            conn.commit()

    conn.commit()
    print(f"✓ Generated enhanced narratives for {len(player_rows)} player-seasons")

    # Show samples
    print("\n" + "=" * 70)
    print("SAMPLE ENHANCED NARRATIVES")
    print("=" * 70)

    # Sample game
    cursor.execute("""
        SELECT game_id, narrative_text
        FROM gold_game_narratives
        WHERE narrative_text IS NOT NULL
          AND LENGTH(narrative_text) > 200
        FETCH FIRST 2 ROWS ONLY
    """)

    print("\nSample Game Narratives:")
    for gid, narrative in cursor.fetchall():
        print(f"\nGame {gid}:")
        print(f"  {narrative[:300]}...")

    # Sample player
    cursor.execute("""
        SELECT full_name, season, narrative_text
        FROM gold_player_season_stats
        WHERE narrative_text IS NOT NULL
          AND points > 40
        FETCH FIRST 2 ROWS ONLY
    """)

    print("\nSample Player Narratives:")
    for name, season, narrative in cursor.fetchall():
        season_str = f"{str(season)[:4]}-{str(season)[4:6]}"
        print(f"\n{name} ({season_str}):")
        print(f"  {narrative}")

    cursor.close()
    conn.close()

    print(f"\nFinished: {datetime.now().isoformat()}")
    print("=" * 70)
    print("\nNext steps:")
    print("  1. Re-generate embeddings: python etl/generate_embeddings.py")
    print("  2. Re-test semantic search to verify improvements")
    print("=" * 70)

if __name__ == "__main__":
    main()
