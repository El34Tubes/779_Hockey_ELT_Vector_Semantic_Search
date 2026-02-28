"""
Generate Narrative Text for Gold Tables
========================================
Reads structured data from gold tables and generates human-readable
narrative text suitable for embedding and semantic search.

Usage:
  python etl/generate_narratives.py              # all narratives
  python etl/generate_narratives.py --limit 100  # first 100 only
"""

import sys, os, argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.db_connect import get_connection


def generate_game_narrative(row):
    """Generate natural language narrative from game data."""
    (game_id, game_date, home_team, away_team, home_score, away_score,
     winner, margin, total_goals, ot_flag, so_flag, total_pens, total_pim,
     home_shots, away_shots, star1_name, star1_team, star2_name, star3_name) = row

    # Build narrative
    narrative = f"On {game_date.strftime('%B %d, %Y')}, "
    narrative += f"{home_team} hosted {away_team}. "

    # Score line
    if winner == 'HOME':
        narrative += f"{home_team} won {home_score}-{away_score}"
    elif winner == 'AWAY':
        narrative += f"{away_team} won {away_score}-{home_score}"
    else:
        narrative += f"The game ended in a {home_score}-{away_score} tie"

    # Overtime/Shootout
    if ot_flag == 'Y':
        narrative += " in overtime" if so_flag == 'N' else " in a shootout"
    narrative += ". "

    # Game characterization
    if total_goals >= 8:
        narrative += "This was a high-scoring offensive showcase. "
    elif total_goals <= 3:
        narrative += "This was a defensive battle with limited scoring. "

    if margin >= 4:
        narrative += f"The winning team dominated with a {margin}-goal margin. "
    elif margin == 1 and ot_flag == 'Y':
        narrative += "The game was decided by a single goal in overtime. "

    # Shots and penalties
    total_shots = (home_shots or 0) + (away_shots or 0)
    if total_shots > 70:
        narrative += f"Both teams were aggressive with {total_shots} total shots on goal. "

    if total_pens >= 10:
        narrative += f"The game was chippy with {total_pens} penalties totaling {total_pim} minutes. "
    elif total_pens <= 2:
        narrative += "The game was played cleanly with minimal penalties. "

    # Three stars
    if star1_name:
        narrative += f"The three stars were {star1_name} ({star1_team})"
        if star2_name:
            narrative += f", {star2_name}"
        if star3_name:
            narrative += f", and {star3_name}"
        narrative += ". "

    return narrative.strip()


def generate_player_narrative(row):
    """Generate narrative for player season stats."""
    (player_id, season, name, pos, games, goals, assists, points,
     plus_minus, pim, shots, pp_goals) = row

    if not name:
        name = f"Player {player_id}"

    season_str = f"{str(season)[:4]}-{str(season)[4:6]}"

    narrative = f"{name}"
    if pos:
        narrative += f", a {pos},"
    narrative += f" played {games} games in the {season_str} season. "

    if goals and assists:
        narrative += f"Offensively, {name.split()[-1] if ' ' in name else name} recorded {goals} goals and {assists} assists for {points} points. "

        if points >= 80:
            narrative += "This was an elite offensive performance. "
        elif points >= 50:
            narrative += "This was a strong offensive season. "

        if pp_goals and pp_goals >= 10:
            narrative += f"On the power play, they contributed {pp_goals} goals. "

    if plus_minus:
        if plus_minus > 15:
            narrative += f"With a plus-minus of +{plus_minus}, they were excellent defensively. "
        elif plus_minus < -10:
            narrative += f"Their plus-minus of {plus_minus} indicates defensive struggles. "

    if shots and goals and shots > 0:
        shot_pct = (goals / shots) * 100
        if shot_pct > 15:
            narrative += f"They shot {shot_pct:.1f}%, showing excellent finishing ability. "

    return narrative.strip()


def generate_team_narrative(row):
    """Generate narrative for team season summary."""
    (team_abbrev, season, team_name, games, wins, losses, ot_losses,
     goals_for, goals_against, goal_diff, gf_pg, ga_pg, points) = row

    season_str = f"{str(season)[:4]}-{str(season)[4:6]}"

    narrative = f"{team_name} in the {season_str} season played {games} games "
    narrative += f"with a record of {wins}-{losses}-{ot_losses}. "

    # Playoff positioning
    if points >= 100:
        narrative += "They were a strong playoff contender. "
    elif points < 70:
        narrative += "They struggled throughout the season. "

    # Offensive/Defensive identity
    if gf_pg >= 3.5:
        narrative += f"Offensively, they averaged {gf_pg:.2f} goals per game, showcasing strong scoring depth. "
    elif gf_pg < 2.5:
        narrative += f"The team struggled to score, averaging only {gf_pg:.2f} goals per game. "

    if ga_pg < 2.5:
        narrative += f"Defensively, they were stingy, allowing just {ga_pg:.2f} goals per game. "
    elif ga_pg >= 3.5:
        narrative += f"They had defensive issues, conceding {ga_pg:.2f} goals per game. "

    # Goal differential
    if goal_diff > 40:
        narrative += f"With a goal differential of +{goal_diff}, they dominated their opponents. "
    elif goal_diff < -40:
        narrative += f"A goal differential of {goal_diff} reflected their struggles. "

    return narrative.strip()


def update_game_narratives(conn, limit=None):
    """Update narrative_text for games."""
    cursor = conn.cursor()

    # Fetch games needing narratives
    sql = """
        SELECT game_id, game_date, home_team_name, away_team_name,
               home_score, away_score, winner, margin, total_goals,
               overtime_flag, shootout_flag, total_penalties, total_pim,
               home_shots, away_shots, star1_name, star1_team, star2_name, star3_name
        FROM gold_game_narratives
        WHERE narrative_text IS NULL OR narrative_text = 'placeholder'
    """
    if limit:
        sql += f" FETCH FIRST {limit} ROWS ONLY"

    cursor.execute(sql)
    games = cursor.fetchall()

    print(f"Generating narratives for {len(games)} games...")

    update_cursor = conn.cursor()
    for i, game_row in enumerate(games):
        narrative = generate_game_narrative(game_row)
        game_id = game_row[0]

        update_cursor.execute(
            "UPDATE gold_game_narratives SET narrative_text = :1 WHERE game_id = :2",
            (narrative, game_id)
        )

        if (i + 1) % 500 == 0:
            conn.commit()
            print(f"  {i+1}/{len(games)} games processed...")

    conn.commit()
    print(f"✓ Generated narratives for {len(games)} games")
    cursor.close()
    update_cursor.close()


def update_player_narratives(conn, limit=None):
    """Update narrative_text for player seasons."""
    cursor = conn.cursor()

    sql = """
        SELECT player_id, season, full_name, position_code, games_played,
               goals, assists, points, plus_minus, pim, shots, pp_goals
        FROM gold_player_season_stats
        WHERE narrative_text IS NULL
    """
    if limit:
        sql += f" FETCH FIRST {limit} ROWS ONLY"

    cursor.execute(sql)
    players = cursor.fetchall()

    print(f"Generating narratives for {len(players)} player-seasons...")

    update_cursor = conn.cursor()
    for i, player_row in enumerate(players):
        narrative = generate_player_narrative(player_row)
        player_id, season = player_row[0], player_row[1]

        update_cursor.execute(
            "UPDATE gold_player_season_stats SET narrative_text = :1 WHERE player_id = :2 AND season = :3",
            (narrative, player_id, season)
        )

        if (i + 1) % 500 == 0:
            conn.commit()
            print(f"  {i+1}/{len(players)} player-seasons processed...")

    conn.commit()
    print(f"✓ Generated narratives for {len(players)} player-seasons")
    cursor.close()
    update_cursor.close()


def update_team_narratives(conn, limit=None):
    """Update narrative_text for team seasons."""
    cursor = conn.cursor()

    sql = """
        SELECT team_abbrev, season, team_name, games_played, wins, losses, ot_losses,
               goals_for, goals_against, goal_diff, goals_per_game, goals_against_pg, points
        FROM gold_team_season_summary
        WHERE narrative_text IS NULL
    """
    if limit:
        sql += f" FETCH FIRST {limit} ROWS ONLY"

    cursor.execute(sql)
    teams = cursor.fetchall()

    print(f"Generating narratives for {len(teams)} team-seasons...")

    update_cursor = conn.cursor()
    for team_row in teams:
        narrative = generate_team_narrative(team_row)
        team_abbrev, season = team_row[0], team_row[1]

        update_cursor.execute(
            "UPDATE gold_team_season_summary SET narrative_text = :1 WHERE team_abbrev = :2 AND season = :3",
            (narrative, team_abbrev, season)
        )

    conn.commit()
    print(f"✓ Generated narratives for {len(teams)} team-seasons")
    cursor.close()
    update_cursor.close()


def main():
    parser = argparse.ArgumentParser(description="Generate narrative text for gold tables")
    parser.add_argument("--limit", type=int, help="Limit number of rows per table")
    args = parser.parse_args()

    print("="*60)
    print("NARRATIVE TEXT GENERATION")
    print(f"Started: {datetime.now().isoformat()}")
    print("="*60)

    conn = get_connection("gold")

    try:
        update_game_narratives(conn, args.limit)
        update_player_narratives(conn, args.limit)
        update_team_narratives(conn, args.limit)
    finally:
        conn.close()

    print(f"\nFinished: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
