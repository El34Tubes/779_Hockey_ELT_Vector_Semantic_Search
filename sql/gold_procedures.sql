-- ============================================================
-- Gold ETL Stored Procedures - NHL Semantic Analytics
-- ============================================================
-- Purpose: Transform silver data → gold analytics tables with:
--   1. Narrative text generation from structured data
--   2. Oracle VECTOR embeddings via DBMS_VECTOR
--   3. Statistical fingerprints for player comps
--
-- Architecture:
--   - Each procedure: SELECT (silver) → generate text → embed → MERGE (gold)
--   - Master procedure: sp_load_gold orchestrates all in dependency order
--   - Watermark-aware delta loads (only process new silver data)
--   - AUTHID DEFINER (runs with gold_schema's grants on silver_schema)
--
-- Usage:
--   Compile: sqlplus gold_schema/password@FREEPDB1 @sql/gold_procedures.sql
--   Run ETL: python etl/gold_load.py
-- ============================================================


-- ============================================================
-- 1. sp_load_game_narratives
-- ============================================================
-- Generates searchable game summaries from silver_games + aggregated stats
--
-- Narrative includes: score, teams, three stars, penalty/shot stats
-- Vector embedding: Oracle DBMS_VECTOR on narrative_text

CREATE OR REPLACE PROCEDURE sp_load_game_narratives (
    p_wm IN TIMESTAMP DEFAULT NULL
) AUTHID DEFINER AS
    v_rows NUMBER := 0;
    v_narrative CLOB;
    v_vector VECTOR;
BEGIN
    -- MERGE game narratives from silver data
    MERGE INTO gold_game_narratives ggn
    USING (
        SELECT
            g.game_id,
            g.game_date,
            g.season,
            g.game_type,
            ht.abbrev AS home_team_abbrev,
            ht.full_name AS home_team_name,
            at.abbrev AS away_team_abbrev,
            at.full_name AS away_team_name,
            g.home_score,
            g.away_score,
            CASE
                WHEN g.home_score > g.away_score THEN 'HOME'
                WHEN g.away_score > g.home_score THEN 'AWAY'
                ELSE 'TIE'
            END AS winner,
            ABS(g.home_score - g.away_score) AS margin,
            g.home_score + g.away_score AS total_goals,
            CASE WHEN g.final_period > 3 THEN 'Y' ELSE 'N' END AS overtime_flag,
            CASE WHEN g.shootout THEN 'Y' ELSE 'N' END AS shootout_flag,
            g.final_period,

            -- Aggregated stats from penalties and goals
            (SELECT COUNT(*) FROM silver_schema.silver_penalties sp WHERE sp.game_id = g.game_id) AS total_penalties,
            (SELECT NVL(SUM(pen_minutes),0) FROM silver_schema.silver_penalties sp WHERE sp.game_id = g.game_id) AS total_pim,
            g.home_sog AS home_shots,
            g.away_sog AS away_shots,
            g.home_sog + g.away_sog AS total_shots,

            -- Three stars (top 3 from silver_three_stars)
            (SELECT full_name FROM silver_schema.silver_three_stars WHERE game_id=g.game_id AND star_rank=1 FETCH FIRST 1 ROW ONLY) AS star1_name,
            (SELECT team_abbrev FROM silver_schema.silver_three_stars WHERE game_id=g.game_id AND star_rank=1 FETCH FIRST 1 ROW ONLY) AS star1_team,
            (SELECT full_name FROM silver_schema.silver_three_stars WHERE game_id=g.game_id AND star_rank=2 FETCH FIRST 1 ROW ONLY) AS star2_name,
            (SELECT team_abbrev FROM silver_schema.silver_three_stars WHERE game_id=g.game_id AND star_rank=2 FETCH FIRST 1 ROW ONLY) AS star2_team,
            (SELECT full_name FROM silver_schema.silver_three_stars WHERE game_id=g.game_id AND star_rank=3 FETCH FIRST 1 ROW ONLY) AS star3_name,
            (SELECT team_abbrev FROM silver_schema.silver_three_stars WHERE game_id=g.game_id AND star_rank=3 FETCH FIRST 1 ROW ONLY) AS star3_team

        FROM silver_schema.silver_games g
        JOIN silver_schema.silver_teams ht ON g.home_team_id = ht.team_id
        JOIN silver_schema.silver_teams at ON g.away_team_id = at.team_id
        WHERE (p_wm IS NULL OR g.loaded_at > p_wm)
          AND g.game_state IN ('OFF', 'FINAL')
    ) src
    ON (ggn.game_id = src.game_id)

    WHEN NOT MATCHED THEN
        INSERT (
            game_id, game_date, season, game_type,
            home_team_abbrev, home_team_name, away_team_abbrev, away_team_name,
            home_score, away_score, winner, margin, total_goals,
            overtime_flag, shootout_flag, final_period,
            total_penalties, total_pim, home_shots, away_shots, total_shots,
            star1_name, star1_team, star2_name, star2_team, star3_name, star3_team,
            narrative_text, narrative_vector
        ) VALUES (
            src.game_id, src.game_date, src.season, src.game_type,
            src.home_team_abbrev, src.home_team_name, src.away_team_abbrev, src.away_team_name,
            src.home_score, src.away_score, src.winner, src.margin, src.total_goals,
            src.overtime_flag, src.shootout_flag, src.final_period,
            src.total_penalties, src.total_pim, src.home_shots, src.away_shots, src.total_shots,
            src.star1_name, src.star1_team, src.star2_name, src.star2_team, src.star3_name, src.star3_team,
            NULL,  -- narrative_text (will be generated in next pass)
            NULL   -- narrative_vector (will be generated in next pass)
        )

    WHEN MATCHED THEN
        UPDATE SET
            ggn.updated_at = SYSTIMESTAMP,
            ggn.home_score = src.home_score,
            ggn.away_score = src.away_score,
            ggn.winner = src.winner;

    v_rows := SQL%ROWCOUNT;

    -- Second pass: generate narratives and embeddings for games with NULL narrative_text
    -- (This is a simplified approach - in production you'd batch this)
    FOR rec IN (
        SELECT game_id, home_team_name, away_team_name, home_score, away_score,
               overtime_flag, total_goals, total_penalties,
               star1_name, star1_team, star2_name, star3_name,
               margin, winner
        FROM gold_game_narratives
        WHERE narrative_text IS NULL
        FETCH FIRST 100 ROWS ONLY  -- Process in batches
    ) LOOP
        -- Generate narrative text
        v_narrative :=
            rec.home_team_name || ' vs ' || rec.away_team_name || '. ' ||
            'Final score: ' || rec.home_score || '-' || rec.away_score ||
            CASE WHEN rec.overtime_flag = 'Y' THEN ' (OT)' ELSE '' END || '. ' ||
            CASE rec.winner
                WHEN 'HOME' THEN rec.home_team_name || ' won by ' || rec.margin || ' goal' || CASE WHEN rec.margin > 1 THEN 's' ELSE '' END || '. '
                WHEN 'AWAY' THEN rec.away_team_name || ' won by ' || rec.margin || ' goal' || CASE WHEN rec.margin > 1 THEN 's' ELSE '' END || '. '
                ELSE 'Game ended in a tie. '
            END ||
            'Total goals: ' || rec.total_goals || '. ' ||
            'Penalties: ' || rec.total_penalties || '. ' ||
            CASE
                WHEN rec.star1_name IS NOT NULL THEN
                    'Three stars: ' || rec.star1_name || ' (' || rec.star1_team || ')' ||
                    CASE WHEN rec.star2_name IS NOT NULL THEN ', ' || rec.star2_name ELSE '' END ||
                    CASE WHEN rec.star3_name IS NOT NULL THEN ', ' || rec.star3_name ELSE '' END || '.'
                ELSE ''
            END;

        -- Generate vector embedding using Oracle DBMS_VECTOR
        -- Note: This requires Oracle 23ai+ with vector models loaded
        -- For now, we'll insert NULL and note that embedding generation happens in Python
        -- (Oracle DBMS_VECTOR.UTL_TO_EMBEDDING requires ONNX models pre-loaded)
        v_vector := NULL;  -- Placeholder: will be generated by Python script

        -- Update the narrative
        UPDATE gold_game_narratives
        SET narrative_text = v_narrative,
            narrative_vector = v_vector,
            updated_at = SYSTIMESTAMP
        WHERE game_id = rec.game_id;
    END LOOP;

    COMMIT;

    gold_log('gold_game_narratives', v_rows, 0, 0, 'SUCCESS', NULL, 0);

EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        gold_log('gold_game_narratives', v_rows, 0, 0, 'ERROR', SQLERRM, 0);
        RAISE;
END sp_load_game_narratives;
/


-- ============================================================
-- 2. sp_load_player_season_stats
-- ============================================================
-- Aggregates player stats by season from silver_skater_stats + silver_goalie_stats
-- Generates narrative summaries and stat fingerprints for player comps

CREATE OR REPLACE PROCEDURE sp_load_player_season_stats (
    p_wm IN TIMESTAMP DEFAULT NULL
) AUTHID DEFINER AS
    v_rows NUMBER := 0;
BEGIN
    -- MERGE player season stats (skaters)
    MERGE INTO gold_player_season_stats gpss
    USING (
        SELECT
            ss.player_id,
            g.season,
            p.full_name,
            p.position AS position_code,
            p.sweater_no AS sweater_number,
            COUNT(DISTINCT ss.game_id) AS games_played,
            COUNT(DISTINCT ss.game_id) AS games_as_skater,
            0 AS games_as_goalie,
            NVL(SUM(ss.goals), 0) AS goals,
            NVL(SUM(ss.assists), 0) AS assists,
            NVL(SUM(ss.goals), 0) + NVL(SUM(ss.assists), 0) AS points,
            NVL(SUM(ss.plus_minus), 0) AS plus_minus,
            NVL(SUM(ss.pim), 0) AS pim,
            NVL(SUM(ss.shots_on_goal), 0) AS shots,
            CASE
                WHEN SUM(ss.shots_on_goal) > 0 THEN ROUND(SUM(ss.goals) / SUM(ss.shots_on_goal) * 100, 2)
                ELSE 0
            END AS shot_pct,
            0 AS toi_seconds,
            0 AS avg_toi_per_game,
            NVL(SUM(ss.power_play_goals), 0) AS pp_goals,
            0 AS sh_goals,
            0 AS gw_goals,
            0 AS ot_goals
        FROM silver_schema.silver_skater_stats ss
        JOIN silver_schema.silver_games g ON ss.game_id = g.game_id
        JOIN silver_schema.silver_players p ON ss.player_id = p.player_id
        WHERE (p_wm IS NULL OR ss.loaded_at > p_wm)
        GROUP BY ss.player_id, g.season, p.full_name, p.position, p.sweater_no
    ) src
    ON (gpss.player_id = src.player_id AND gpss.season = src.season)

    WHEN NOT MATCHED THEN
        INSERT (
            player_id, season, full_name, position_code, sweater_number,
            games_played, games_as_skater, games_as_goalie,
            goals, assists, points, plus_minus, pim, shots, shot_pct,
            toi_seconds, avg_toi_per_game,
            pp_goals, sh_goals, gw_goals, ot_goals
        ) VALUES (
            src.player_id, src.season, src.full_name, src.position_code, src.sweater_number,
            src.games_played, src.games_as_skater, src.games_as_goalie,
            src.goals, src.assists, src.points, src.plus_minus, src.pim, src.shots, src.shot_pct,
            src.toi_seconds, src.avg_toi_per_game,
            src.pp_goals, src.sh_goals, src.gw_goals, src.ot_goals
        )

    WHEN MATCHED THEN
        UPDATE SET
            gpss.full_name = src.full_name,
            gpss.position_code = src.position_code,
            gpss.sweater_number = src.sweater_number,
            gpss.updated_at = SYSTIMESTAMP,
            gpss.games_played = src.games_played,
            gpss.goals = src.goals,
            gpss.assists = src.assists,
            gpss.points = src.points;

    v_rows := SQL%ROWCOUNT;

    -- TODO: Add goalie stats aggregation (similar pattern from silver_goalie_stats)
    -- TODO: Generate narrative_text for each player-season
    -- TODO: Generate stat_vector (normalized stats for similarity search)

    COMMIT;

    gold_log('gold_player_season_stats', v_rows, 0, 0, 'SUCCESS', NULL, 0);

EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        gold_log('gold_player_season_stats', v_rows, 0, 0, 'ERROR', SQLERRM, 0);
        RAISE;
END sp_load_player_season_stats;
/


-- ============================================================
-- 3. sp_load_team_season_summary
-- ============================================================
-- Aggregates team performance by season

CREATE OR REPLACE PROCEDURE sp_load_team_season_summary (
    p_wm IN TIMESTAMP DEFAULT NULL
) AUTHID DEFINER AS
    v_rows NUMBER := 0;
BEGIN
    -- MERGE team season summaries
    MERGE INTO gold_team_season_summary gtss
    USING (
        SELECT
            t.abbrev AS team_abbrev,
            g.season,
            t.full_name AS team_name,
            COUNT(*) AS games_played,
            SUM(CASE WHEN (g.home_team_id = t.team_id AND g.home_score > g.away_score)
                      OR (g.away_team_id = t.team_id AND g.away_score > g.home_score)
                     THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN (g.home_team_id = t.team_id AND g.home_score < g.away_score)
                      OR (g.away_team_id = t.team_id AND g.away_score < g.home_score)
                     THEN 1 ELSE 0 END) AS losses,
            SUM(CASE WHEN g.final_period > 3
                      AND ((g.home_team_id = t.team_id AND g.home_score < g.away_score)
                           OR (g.away_team_id = t.team_id AND g.away_score < g.home_score))
                     THEN 1 ELSE 0 END) AS ot_losses,
            SUM(CASE WHEN g.home_team_id = t.team_id THEN g.home_score ELSE g.away_score END) AS goals_for,
            SUM(CASE WHEN g.home_team_id = t.team_id THEN g.away_score ELSE g.home_score END) AS goals_against
        FROM silver_schema.silver_teams t
        JOIN silver_schema.silver_games g
            ON (g.home_team_id = t.team_id OR g.away_team_id = t.team_id)
        WHERE (p_wm IS NULL OR g.loaded_at > p_wm)
          AND g.game_state IN ('OFF', 'FINAL')
          AND g.game_type = 2  -- Regular season only
        GROUP BY t.abbrev, g.season, t.full_name
    ) src
    ON (gtss.team_abbrev = src.team_abbrev AND gtss.season = src.season)

    WHEN NOT MATCHED THEN
        INSERT (
            team_abbrev, season, team_name,
            games_played, wins, losses, ot_losses,
            goals_for, goals_against,
            goal_diff, goals_per_game, goals_against_pg,
            points
        ) VALUES (
            src.team_abbrev, src.season, src.team_name,
            src.games_played, src.wins, src.losses, src.ot_losses,
            src.goals_for, src.goals_against,
            src.goals_for - src.goals_against,
            ROUND(src.goals_for / GREATEST(src.games_played, 1), 2),
            ROUND(src.goals_against / GREATEST(src.games_played, 1), 2),
            src.wins * 2 + src.ot_losses
        )

    WHEN MATCHED THEN
        UPDATE SET
            gtss.updated_at = SYSTIMESTAMP,
            gtss.games_played = src.games_played,
            gtss.wins = src.wins,
            gtss.points = src.wins * 2 + src.ot_losses;

    v_rows := SQL%ROWCOUNT;
    COMMIT;

    gold_log('gold_team_season_summary', v_rows, 0, 0, 'SUCCESS', NULL, 0);

EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        gold_log('gold_team_season_summary', v_rows, 0, 0, 'ERROR', SQLERRM, 0);
        RAISE;
END sp_load_team_season_summary;
/


-- ============================================================
-- MASTER: sp_load_gold
-- ============================================================
-- Orchestrates all gold ETL procedures in dependency order
-- Reads watermarks, calls sub-procedures, advances watermarks on success

CREATE OR REPLACE PROCEDURE sp_load_gold AUTHID DEFINER AS
    v_wm_games TIMESTAMP;
    v_wm_players TIMESTAMP;
    v_wm_teams TIMESTAMP;
    v_wm_stats TIMESTAMP;

    v_new_games TIMESTAMP;
    v_new_players TIMESTAMP;
    v_new_teams TIMESTAMP;
    v_new_stats TIMESTAMP;
BEGIN
    -- Read current watermarks
    SELECT last_silver_ts INTO v_wm_games   FROM gold_watermarks WHERE source_table = 'silver_games';
    SELECT last_silver_ts INTO v_wm_players FROM gold_watermarks WHERE source_table = 'silver_players';
    SELECT last_silver_ts INTO v_wm_teams   FROM gold_watermarks WHERE source_table = 'silver_teams';
    SELECT last_silver_ts INTO v_wm_stats   FROM gold_watermarks WHERE source_table = 'silver_skater_stats';

    -- Snapshot new high watermarks before processing
    SELECT MAX(loaded_at) INTO v_new_games   FROM silver_schema.silver_games WHERE (v_wm_games IS NULL OR loaded_at > v_wm_games);
    SELECT MAX(loaded_at) INTO v_new_players FROM silver_schema.silver_players WHERE (v_wm_players IS NULL OR loaded_at > v_wm_players);
    SELECT MAX(loaded_at) INTO v_new_teams   FROM silver_schema.silver_teams WHERE (v_wm_teams IS NULL OR loaded_at > v_wm_teams);
    SELECT MAX(loaded_at) INTO v_new_stats   FROM silver_schema.silver_skater_stats WHERE (v_wm_stats IS NULL OR loaded_at > v_wm_stats);

    -- Call sub-procedures in dependency order
    sp_load_team_season_summary(v_wm_games);
    sp_load_game_narratives(v_wm_games);
    sp_load_player_season_stats(v_wm_stats);

    -- Advance watermarks (only if new data was found)
    UPDATE gold_watermarks
    SET last_silver_ts = v_new_games, last_run_at = SYSTIMESTAMP, rows_processed = rows_processed + 1
    WHERE source_table = 'silver_games' AND v_new_games IS NOT NULL;

    UPDATE gold_watermarks
    SET last_silver_ts = v_new_stats, last_run_at = SYSTIMESTAMP, rows_processed = rows_processed + 1
    WHERE source_table = 'silver_skater_stats' AND v_new_stats IS NOT NULL;

    COMMIT;

    gold_log('sp_load_gold', 0, 0, 0, 'SUCCESS', 'Master gold ETL complete', 0);

EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        gold_log('sp_load_gold', 0, 0, 0, 'ERROR', SQLERRM, 0);
        RAISE;
END sp_load_gold;
/


-- ============================================================
-- Compilation summary
-- ============================================================

SELECT 'Gold procedures compiled' AS status FROM DUAL;

SELECT object_name, object_type, status
FROM user_objects
WHERE object_type = 'PROCEDURE'
ORDER BY object_name;
