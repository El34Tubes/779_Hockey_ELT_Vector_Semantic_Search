-- ============================================================
-- Silver Layer Stored Procedures
-- Bronze JSON (OSON) → Silver via JSON_TABLE + MERGE (delta-aware)
--
-- Architecture:
--   • One procedure per silver entity
--   • All procedures receive the pre-read watermark (p_wm) from master
--   • MERGE ensures idempotency — safe to re-run
--   • Master proc (sp_load_silver) reads watermarks, calls subs in order,
--     then advances watermarks only after all subs succeed
--
-- NOTE: JSON field paths are derived from NHL / ESPN API exploration.
--       If new ORA-0932x errors appear, query the bronze JSON directly
--       to verify the path: SELECT JSON_VALUE(raw_response, '$.field') FROM ...
--
-- Prerequisite: run sql/setup_silver_grants.sql as SYSTEM first.
-- ============================================================


-- ── 1. sp_load_games ──────────────────────────────────────────
-- Source : bronze_schema.bronze_nhl_game_detail → landing_json
-- Target : silver_games
-- Filter : gameType=2 (regular season), gameState IN ('OFF','FINAL')
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE PROCEDURE sp_load_games (p_wm IN TIMESTAMP DEFAULT NULL) AS
    v_rows  NUMBER;
BEGIN
    MERGE INTO silver_games sg
    USING (
        SELECT
            jt.game_id,
            TO_DATE(jt.game_date_s, 'YYYY-MM-DD')           AS game_date,
            jt.season,
            jt.game_type,
            jt.game_state,
            jt.home_team,
            jt.away_team,
            jt.home_score,
            jt.away_score,
            jt.home_sog,
            jt.away_sog,
            jt.last_period_type,
            jt.venue,
            jt.venue_location,
            TO_TIMESTAMP(REPLACE(jt.start_time_utc, 'Z', ''),
                         'YYYY-MM-DD"T"HH24:MI:SS')          AS start_time_utc
        FROM   bronze_schema.bronze_nhl_game_detail bngd
        CROSS JOIN JSON_TABLE(bngd.landing_json, '$' COLUMNS (
            game_id           NUMBER         PATH '$.id',
            game_date_s       VARCHAR2(20)   PATH '$.gameDate',
            season            NUMBER         PATH '$.season',
            game_type         NUMBER         PATH '$.gameType',
            game_state        VARCHAR2(20)   PATH '$.gameState',
            home_team         VARCHAR2(10)   PATH '$.homeTeam.abbrev',
            away_team         VARCHAR2(10)   PATH '$.awayTeam.abbrev',
            home_score        NUMBER         PATH '$.homeTeam.score',
            away_score        NUMBER         PATH '$.awayTeam.score',
            home_sog          NUMBER         PATH '$.homeTeam.sog',
            away_sog          NUMBER         PATH '$.awayTeam.sog',
            last_period_type  VARCHAR2(10)   PATH '$.periodDescriptor.periodType',
            venue             VARCHAR2(200)  PATH '$.venue.default',
            venue_location    VARCHAR2(200)  PATH '$.venueLocation.default',
            start_time_utc    VARCHAR2(30)   PATH '$.startTimeUTC'
        )) jt
        WHERE  (p_wm IS NULL OR bngd.loaded_at > p_wm)
          AND  jt.game_type  = 2
          AND  jt.game_state IN ('OFF', 'FINAL')
          AND  jt.game_id    IS NOT NULL
          AND  jt.home_team  IS NOT NULL
          AND  jt.away_team  IS NOT NULL
    ) src
    ON (sg.game_id = src.game_id)
    WHEN NOT MATCHED THEN INSERT (
        game_id, game_date, season, game_type, game_state,
        home_team, away_team, home_score, away_score,
        home_sog, away_sog, last_period_type,
        venue, venue_location, start_time_utc
    ) VALUES (
        src.game_id, src.game_date, src.season, src.game_type, src.game_state,
        src.home_team, src.away_team, src.home_score, src.away_score,
        src.home_sog, src.away_sog, src.last_period_type,
        src.venue, src.venue_location, src.start_time_utc
    )
    WHEN MATCHED THEN UPDATE SET
        sg.home_score       = src.home_score,
        sg.away_score       = src.away_score,
        sg.home_sog         = src.home_sog,
        sg.away_sog         = src.away_sog,
        sg.game_state       = src.game_state,
        sg.last_period_type = src.last_period_type,
        sg.updated_at       = SYSTIMESTAMP;

    v_rows := SQL%ROWCOUNT;
    silver_log('silver_games', v_rows, v_rows, 0, 'SUCCESS');
    COMMIT;
EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        silver_log('silver_games', 0, 0, 0, 'ERROR', SUBSTR(SQLERRM, 1, 4000));
        RAISE;
END sp_load_games;
/


-- ── 2. sp_load_players ────────────────────────────────────────
-- Source : bronze_schema.bronze_nhl_game_detail → boxscore_json.playerByGameStats.*Team.{forwards|defense|goalies}[*]
-- Target : silver_players  (incremental dim — upsert on sweater number change)
-- Note   : Must run BEFORE sp_load_goals / sp_load_skater_stats / sp_load_goalie_stats
--          because those tables FK back to silver_players.player_id
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE PROCEDURE sp_load_players (p_wm IN TIMESTAMP DEFAULT NULL) AS
    v_rows  NUMBER;
BEGIN
    MERGE INTO silver_players sp
    USING (
        -- Deduplicate across all 6 position groups (home+away × forwards+defense+goalies)
        -- GROUP BY player_id keeps most recently seen sweater number via MAX
        SELECT
            player_id,
            MAX(first_name)  AS first_name,
            MAX(last_name)   AS last_name,
            MAX(position)    AS position,
            MAX(sweater_no)  AS sweater_no
        FROM (
            SELECT jt.player_id,
                   CASE WHEN INSTR(jt.player_name, ' ') > 0
                        THEN SUBSTR(jt.player_name, 1, INSTR(jt.player_name, ' ', -1) - 1)
                        ELSE NULL END AS first_name,
                   CASE WHEN INSTR(jt.player_name, ' ') > 0
                        THEN SUBSTR(jt.player_name, INSTR(jt.player_name, ' ', -1) + 1)
                        ELSE jt.player_name END AS last_name,
                   jt.position, jt.sweater_no
            FROM   bronze_schema.bronze_nhl_game_detail bngd
            CROSS JOIN JSON_TABLE(bngd.boxscore_json,
                '$.playerByGameStats.homeTeam.forwards[*]' COLUMNS (
                    player_id  NUMBER        PATH '$.playerId',
                    player_name VARCHAR2(155) PATH '$.name.default',
                    position   VARCHAR2(5)   PATH '$.position',
                    sweater_no NUMBER        PATH '$.sweaterNumber')) jt
            WHERE  (p_wm IS NULL OR bngd.loaded_at > p_wm) AND jt.player_id IS NOT NULL
            UNION ALL
            SELECT jt.player_id,
                   CASE WHEN INSTR(jt.player_name, ' ') > 0
                        THEN SUBSTR(jt.player_name, 1, INSTR(jt.player_name, ' ', -1) - 1)
                        ELSE NULL END AS first_name,
                   CASE WHEN INSTR(jt.player_name, ' ') > 0
                        THEN SUBSTR(jt.player_name, INSTR(jt.player_name, ' ', -1) + 1)
                        ELSE jt.player_name END AS last_name,
                   jt.position, jt.sweater_no
            FROM   bronze_schema.bronze_nhl_game_detail bngd
            CROSS JOIN JSON_TABLE(bngd.boxscore_json,
                '$.playerByGameStats.homeTeam.defense[*]' COLUMNS (
                    player_id  NUMBER        PATH '$.playerId',
                    player_name VARCHAR2(155) PATH '$.name.default',
                    position   VARCHAR2(5)   PATH '$.position',
                    sweater_no NUMBER        PATH '$.sweaterNumber')) jt
            WHERE  (p_wm IS NULL OR bngd.loaded_at > p_wm) AND jt.player_id IS NOT NULL
            UNION ALL
            SELECT jt.player_id,
                   CASE WHEN INSTR(jt.player_name, ' ') > 0
                        THEN SUBSTR(jt.player_name, 1, INSTR(jt.player_name, ' ', -1) - 1)
                        ELSE NULL END AS first_name,
                   CASE WHEN INSTR(jt.player_name, ' ') > 0
                        THEN SUBSTR(jt.player_name, INSTR(jt.player_name, ' ', -1) + 1)
                        ELSE jt.player_name END AS last_name,
                   'G' AS position, jt.sweater_no
            FROM   bronze_schema.bronze_nhl_game_detail bngd
            CROSS JOIN JSON_TABLE(bngd.boxscore_json,
                '$.playerByGameStats.homeTeam.goalies[*]' COLUMNS (
                    player_id  NUMBER        PATH '$.playerId',
                    player_name VARCHAR2(155) PATH '$.name.default',
                    sweater_no NUMBER        PATH '$.sweaterNumber')) jt
            WHERE  (p_wm IS NULL OR bngd.loaded_at > p_wm) AND jt.player_id IS NOT NULL
            UNION ALL
            SELECT jt.player_id,
                   CASE WHEN INSTR(jt.player_name, ' ') > 0
                        THEN SUBSTR(jt.player_name, 1, INSTR(jt.player_name, ' ', -1) - 1)
                        ELSE NULL END AS first_name,
                   CASE WHEN INSTR(jt.player_name, ' ') > 0
                        THEN SUBSTR(jt.player_name, INSTR(jt.player_name, ' ', -1) + 1)
                        ELSE jt.player_name END AS last_name,
                   jt.position, jt.sweater_no
            FROM   bronze_schema.bronze_nhl_game_detail bngd
            CROSS JOIN JSON_TABLE(bngd.boxscore_json,
                '$.playerByGameStats.awayTeam.forwards[*]' COLUMNS (
                    player_id  NUMBER        PATH '$.playerId',
                    player_name VARCHAR2(155) PATH '$.name.default',
                    position   VARCHAR2(5)   PATH '$.position',
                    sweater_no NUMBER        PATH '$.sweaterNumber')) jt
            WHERE  (p_wm IS NULL OR bngd.loaded_at > p_wm) AND jt.player_id IS NOT NULL
            UNION ALL
            SELECT jt.player_id,
                   CASE WHEN INSTR(jt.player_name, ' ') > 0
                        THEN SUBSTR(jt.player_name, 1, INSTR(jt.player_name, ' ', -1) - 1)
                        ELSE NULL END AS first_name,
                   CASE WHEN INSTR(jt.player_name, ' ') > 0
                        THEN SUBSTR(jt.player_name, INSTR(jt.player_name, ' ', -1) + 1)
                        ELSE jt.player_name END AS last_name,
                   jt.position, jt.sweater_no
            FROM   bronze_schema.bronze_nhl_game_detail bngd
            CROSS JOIN JSON_TABLE(bngd.boxscore_json,
                '$.playerByGameStats.awayTeam.defense[*]' COLUMNS (
                    player_id  NUMBER        PATH '$.playerId',
                    player_name VARCHAR2(155) PATH '$.name.default',
                    position   VARCHAR2(5)   PATH '$.position',
                    sweater_no NUMBER        PATH '$.sweaterNumber')) jt
            WHERE  (p_wm IS NULL OR bngd.loaded_at > p_wm) AND jt.player_id IS NOT NULL
            UNION ALL
            SELECT jt.player_id,
                   CASE WHEN INSTR(jt.player_name, ' ') > 0
                        THEN SUBSTR(jt.player_name, 1, INSTR(jt.player_name, ' ', -1) - 1)
                        ELSE NULL END AS first_name,
                   CASE WHEN INSTR(jt.player_name, ' ') > 0
                        THEN SUBSTR(jt.player_name, INSTR(jt.player_name, ' ', -1) + 1)
                        ELSE jt.player_name END AS last_name,
                   'G' AS position, jt.sweater_no
            FROM   bronze_schema.bronze_nhl_game_detail bngd
            CROSS JOIN JSON_TABLE(bngd.boxscore_json,
                '$.playerByGameStats.awayTeam.goalies[*]' COLUMNS (
                    player_id  NUMBER        PATH '$.playerId',
                    player_name VARCHAR2(155) PATH '$.name.default',
                    sweater_no NUMBER        PATH '$.sweaterNumber')) jt
            WHERE  (p_wm IS NULL OR bngd.loaded_at > p_wm) AND jt.player_id IS NOT NULL
        )
        GROUP BY player_id
    ) src
    ON (sp.player_id = src.player_id)
    WHEN NOT MATCHED THEN INSERT (player_id, first_name, last_name, position, sweater_no)
        VALUES (src.player_id, src.first_name, src.last_name, src.position, src.sweater_no)
    WHEN MATCHED THEN UPDATE SET
        sp.first_name = src.first_name,
        sp.last_name = src.last_name,
        sp.position = src.position,
        sp.sweater_no = src.sweater_no,
        sp.updated_at = SYSTIMESTAMP;

    v_rows := SQL%ROWCOUNT;
    silver_log('silver_players', v_rows, v_rows, 0, 'SUCCESS');
    COMMIT;
EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        silver_log('silver_players', 0, 0, 0, 'ERROR', SUBSTR(SQLERRM, 1, 4000));
        RAISE;
END sp_load_players;
/


-- ── 3. sp_load_goals ──────────────────────────────────────────
-- Source : bronze_schema.bronze_nhl_game_detail → landing_json.summary.scoring[*].goals[*]
-- Target : silver_goals
-- Note   : Nested JSON_TABLE: scoring periods → goals within each period
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE PROCEDURE sp_load_goals (p_wm IN TIMESTAMP DEFAULT NULL) AS
    v_rows  NUMBER;
BEGIN
    MERGE INTO silver_goals sg
    USING (
        SELECT
            bngd.game_id,
            jt.period_num        AS period,
            jt.time_in_period,
            jt.event_id,
            jt.scorer_id,
            jt.scorer_first,
            jt.scorer_last,
            jt.team_abbrev,
            jt.strength,
            jt.shot_type,
            jt.home_score,
            jt.away_score,
            jt.goals_to_date,
            jt.assist1_id,
            jt.assist1_first,
            jt.assist1_last,
            jt.assist2_id,
            jt.assist2_first,
            jt.assist2_last
        FROM   bronze_schema.bronze_nhl_game_detail bngd
        CROSS JOIN JSON_TABLE(bngd.landing_json, '$.summary.scoring[*]' COLUMNS (
            period_num      NUMBER        PATH '$.periodDescriptor.number',
            NESTED PATH '$.goals[*]' COLUMNS (
                event_id        NUMBER        PATH '$.eventId',
                time_in_period  VARCHAR2(10)  PATH '$.timeInPeriod',
                scorer_id       NUMBER        PATH '$.scoringPlayerId',
                scorer_first    VARCHAR2(50)  PATH '$.firstName.default',
                scorer_last     VARCHAR2(100) PATH '$.lastName.default',
                team_abbrev     VARCHAR2(10)  PATH '$.teamAbbrev',
                strength        VARCHAR2(20)  PATH '$.strength',
                shot_type       VARCHAR2(30)  PATH '$.shotType',
                home_score      NUMBER        PATH '$.homeScore',
                away_score      NUMBER        PATH '$.awayScore',
                goals_to_date   NUMBER        PATH '$.goalsToDate',
                assist1_id      NUMBER        PATH '$.assists[0].playerId',
                assist1_first   VARCHAR2(50)  PATH '$.assists[0].firstName.default',
                assist1_last    VARCHAR2(100) PATH '$.assists[0].lastName.default',
                assist2_id      NUMBER        PATH '$.assists[1].playerId',
                assist2_first   VARCHAR2(50)  PATH '$.assists[1].firstName.default',
                assist2_last    VARCHAR2(100) PATH '$.assists[1].lastName.default'
            )
        )) jt
        WHERE  (p_wm IS NULL OR bngd.loaded_at > p_wm)
          AND  jt.event_id  IS NOT NULL
          -- Only insert if parent game exists in silver_games
          AND  EXISTS (SELECT 1 FROM silver_games sg2 WHERE sg2.game_id = bngd.game_id)
    ) src
    ON (sg.game_id = src.game_id AND sg.event_id = src.event_id)
    WHEN NOT MATCHED THEN INSERT (
        game_id, period, time_in_period, event_id,
        scorer_id, scorer_first, scorer_last, team_abbrev,
        strength, shot_type, home_score, away_score, goals_to_date,
        assist1_id, assist1_first, assist1_last,
        assist2_id, assist2_first, assist2_last
    ) VALUES (
        src.game_id, src.period, src.time_in_period, src.event_id,
        src.scorer_id, src.scorer_first, src.scorer_last, src.team_abbrev,
        src.strength, src.shot_type, src.home_score, src.away_score, src.goals_to_date,
        src.assist1_id, src.assist1_first, src.assist1_last,
        src.assist2_id, src.assist2_first, src.assist2_last
    )
    WHEN MATCHED THEN UPDATE SET sg.updated_at = SYSTIMESTAMP;

    v_rows := SQL%ROWCOUNT;
    silver_log('silver_goals', v_rows, v_rows, 0, 'SUCCESS');
    COMMIT;
EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        silver_log('silver_goals', 0, 0, 0, 'ERROR', SUBSTR(SQLERRM, 1, 4000));
        RAISE;
END sp_load_goals;
/


-- ── 4. sp_load_penalties ──────────────────────────────────────
-- Source : bronze_schema.bronze_nhl_game_detail → landing_json.summary.penalties[*].penalties[*]
-- Target : silver_penalties
-- Note   : Nested JSON_TABLE: penalty periods → calls within each period
--          committedByPlayer / drawnBy may be object or simple string in API;
--          paths below assume object form. Verify against bronze if NULL.
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE PROCEDURE sp_load_penalties (p_wm IN TIMESTAMP DEFAULT NULL) AS
    v_rows  NUMBER;
BEGIN
    INSERT INTO silver_penalties (
        game_id, period, time_in_period, team_abbrev,
        penalized_first, penalized_last, penalized_no,
        drawn_first, drawn_last, drawn_no,
        penalty_type, duration, desc_key
    )
    SELECT
        bngd.game_id,
        jt.period_num,
        jt.time_in_period,
        jt.team_abbrev,
        jt.penalized_first,
        jt.penalized_last,
        jt.penalized_no,
        jt.drawn_first,
        jt.drawn_last,
        jt.drawn_no,
        jt.penalty_type,
        jt.duration,
        jt.desc_key
    FROM   bronze_schema.bronze_nhl_game_detail bngd
    CROSS JOIN JSON_TABLE(bngd.landing_json, '$.summary.penalties[*]' COLUMNS (
        period_num      NUMBER        PATH '$.periodDescriptor.number',
        NESTED PATH '$.penalties[*]' COLUMNS (
            time_in_period   VARCHAR2(10)  PATH '$.timeInPeriod',
            team_abbrev      VARCHAR2(10)  PATH '$.teamAbbrev',
            penalized_first  VARCHAR2(50)  PATH '$.committedByPlayer.firstName.default',
            penalized_last   VARCHAR2(100) PATH '$.committedByPlayer.lastName.default',
            penalized_no     NUMBER        PATH '$.committedByPlayer.sweaterNumber',
            drawn_first      VARCHAR2(50)  PATH '$.drawnBy.firstName.default',
            drawn_last       VARCHAR2(100) PATH '$.drawnBy.lastName.default',
            drawn_no         NUMBER        PATH '$.drawnBy.sweaterNumber',
            penalty_type     VARCHAR2(10)  PATH '$.type',
            duration         NUMBER        PATH '$.duration',
            desc_key         VARCHAR2(100) PATH '$.descKey'
        )
    )) jt
    WHERE  (p_wm IS NULL OR bngd.loaded_at > p_wm)
      AND  EXISTS (SELECT 1 FROM silver_games sg WHERE sg.game_id = bngd.game_id)
      -- Skip rows already loaded for this game (no UNIQUE on penalties — use game presence)
      AND  NOT EXISTS (
               SELECT 1 FROM silver_penalties sp2
               WHERE sp2.game_id = bngd.game_id
           );

    v_rows := SQL%ROWCOUNT;
    silver_log('silver_penalties', v_rows, v_rows, 0, 'SUCCESS');
    COMMIT;
EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        silver_log('silver_penalties', 0, 0, 0, 'ERROR', SUBSTR(SQLERRM, 1, 4000));
        RAISE;
END sp_load_penalties;
/


-- ── 5. sp_load_three_stars ────────────────────────────────────
-- Source : bronze_schema.bronze_nhl_game_detail → landing_json.summary.threeStars[*]
-- Target : silver_three_stars
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE PROCEDURE sp_load_three_stars (p_wm IN TIMESTAMP DEFAULT NULL) AS
    v_rows  NUMBER;
BEGIN
    MERGE INTO silver_three_stars ts
    USING (
        SELECT
            bngd.game_id,
            jt.star_rank,
            jt.player_id,
            jt.player_name,
            jt.team_abbrev,
            jt.position,
            jt.sweater_no,
            jt.goals,
            jt.assists,
            jt.points
        FROM   bronze_schema.bronze_nhl_game_detail bngd
        CROSS JOIN JSON_TABLE(bngd.landing_json, '$.summary.threeStars[*]' COLUMNS (
            star_rank    NUMBER        PATH '$.star',
            player_id    NUMBER        PATH '$.playerId',
            player_name  VARCHAR2(100) PATH '$.name.default',
            team_abbrev  VARCHAR2(10)  PATH '$.teamAbbrev',
            position     VARCHAR2(5)   PATH '$.position',
            sweater_no   NUMBER        PATH '$.sweaterNumber',
            goals        NUMBER        PATH '$.goals',
            assists      NUMBER        PATH '$.assists',
            points       NUMBER        PATH '$.points'
        )) jt
        WHERE  (p_wm IS NULL OR bngd.loaded_at > p_wm)
          AND  jt.star_rank IS NOT NULL
          AND  EXISTS (SELECT 1 FROM silver_games sg WHERE sg.game_id = bngd.game_id)
    ) src
    ON (ts.game_id = src.game_id AND ts.star_rank = src.star_rank)
    WHEN NOT MATCHED THEN INSERT (
        game_id, star_rank, player_id, player_name, team_abbrev,
        position, sweater_no, goals, assists, points
    ) VALUES (
        src.game_id, src.star_rank, src.player_id, src.player_name, src.team_abbrev,
        src.position, src.sweater_no, src.goals, src.assists, src.points
    )
    WHEN MATCHED THEN UPDATE SET ts.updated_at = SYSTIMESTAMP;

    v_rows := SQL%ROWCOUNT;
    silver_log('silver_three_stars', v_rows, v_rows, 0, 'SUCCESS');
    COMMIT;
EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        silver_log('silver_three_stars', 0, 0, 0, 'ERROR', SUBSTR(SQLERRM, 1, 4000));
        RAISE;
END sp_load_three_stars;
/


-- ── 6. sp_load_skater_stats ───────────────────────────────────
-- Source : bronze_schema.bronze_nhl_game_detail → boxscore_json.playerByGameStats.*Team.{forwards|defense}[*]
-- Target : silver_skater_stats
-- Note   : JSON_VALUE() pulls team abbrev from the top-level boxscore object
--          alongside each position group's player rows.
--          Field $.blockedAttempts = blocked shots; verify if different in data.
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE PROCEDURE sp_load_skater_stats (p_wm IN TIMESTAMP DEFAULT NULL) AS
    v_rows  NUMBER;
BEGIN
    MERGE INTO silver_skater_stats ss
    USING (
        SELECT game_id, team_abbrev, home_away, player_id,
               first_name, last_name, position, sweater_no,
               goals, assists, points, plus_minus, pim, hits,
               pp_goals, shots, blocked, giveaways, takeaways,
               shifts, toi, faceoff_pct
        FROM (
            -- Home forwards
            SELECT bngd.game_id,
                   JSON_VALUE(bngd.boxscore_json, '$.homeTeam.abbrev') AS team_abbrev,
                   'H'   AS home_away,
                   jt.player_id,
                   CASE WHEN INSTR(jt.player_name, ' ') > 0
                        THEN SUBSTR(jt.player_name, 1, INSTR(jt.player_name, ' ', -1) - 1)
                        ELSE NULL END AS first_name,
                   CASE WHEN INSTR(jt.player_name, ' ') > 0
                        THEN SUBSTR(jt.player_name, INSTR(jt.player_name, ' ', -1) + 1)
                        ELSE jt.player_name END AS last_name,
                   jt.position, jt.sweater_no,
                   jt.goals, jt.assists, jt.points, jt.plus_minus, jt.pim, jt.hits,
                   jt.pp_goals, jt.shots, jt.blocked, jt.giveaways, jt.takeaways,
                   jt.shifts, jt.toi, jt.faceoff_pct
            FROM   bronze_schema.bronze_nhl_game_detail bngd
            CROSS JOIN JSON_TABLE(bngd.boxscore_json,
                '$.playerByGameStats.homeTeam.forwards[*]' COLUMNS (
                    player_id   NUMBER        PATH '$.playerId',
                    player_name VARCHAR2(155) PATH '$.name.default',
                    position    VARCHAR2(5)   PATH '$.position',
                    sweater_no  NUMBER        PATH '$.sweaterNumber',
                    goals       NUMBER        PATH '$.goals',
                    assists     NUMBER        PATH '$.assists',
                    points      NUMBER        PATH '$.points',
                    plus_minus  NUMBER        PATH '$.plusMinus',
                    pim         NUMBER        PATH '$.pim',
                    hits        NUMBER        PATH '$.hits',
                    pp_goals    NUMBER        PATH '$.powerPlayGoals',
                    shots       NUMBER        PATH '$.shots',
                    blocked     NUMBER        PATH '$.blockedAttempts',
                    giveaways   NUMBER        PATH '$.giveaways',
                    takeaways   NUMBER        PATH '$.takeaways',
                    shifts      NUMBER        PATH '$.shifts',
                    toi         VARCHAR2(10)  PATH '$.toi',
                    faceoff_pct NUMBER        PATH '$.faceoffWinningPctg'
                )) jt
            WHERE (p_wm IS NULL OR bngd.loaded_at > p_wm) AND jt.player_id IS NOT NULL
            UNION ALL
            -- Home defense
            SELECT bngd.game_id,
                   JSON_VALUE(bngd.boxscore_json, '$.homeTeam.abbrev') AS team_abbrev,
                   'H',
                   jt.player_id,
                   CASE WHEN INSTR(jt.player_name, ' ') > 0
                        THEN SUBSTR(jt.player_name, 1, INSTR(jt.player_name, ' ', -1) - 1)
                        ELSE NULL END AS first_name,
                   CASE WHEN INSTR(jt.player_name, ' ') > 0
                        THEN SUBSTR(jt.player_name, INSTR(jt.player_name, ' ', -1) + 1)
                        ELSE jt.player_name END AS last_name,
                   jt.position, jt.sweater_no,
                   jt.goals, jt.assists, jt.points, jt.plus_minus, jt.pim, jt.hits,
                   jt.pp_goals, jt.shots, jt.blocked, jt.giveaways, jt.takeaways,
                   jt.shifts, jt.toi, jt.faceoff_pct
            FROM   bronze_schema.bronze_nhl_game_detail bngd
            CROSS JOIN JSON_TABLE(bngd.boxscore_json,
                '$.playerByGameStats.homeTeam.defense[*]' COLUMNS (
                    player_id   NUMBER        PATH '$.playerId',
                    player_name VARCHAR2(155) PATH '$.name.default',
                    position    VARCHAR2(5)   PATH '$.position',
                    sweater_no  NUMBER        PATH '$.sweaterNumber',
                    goals       NUMBER        PATH '$.goals',
                    assists     NUMBER        PATH '$.assists',
                    points      NUMBER        PATH '$.points',
                    plus_minus  NUMBER        PATH '$.plusMinus',
                    pim         NUMBER        PATH '$.pim',
                    hits        NUMBER        PATH '$.hits',
                    pp_goals    NUMBER        PATH '$.powerPlayGoals',
                    shots       NUMBER        PATH '$.shots',
                    blocked     NUMBER        PATH '$.blockedAttempts',
                    giveaways   NUMBER        PATH '$.giveaways',
                    takeaways   NUMBER        PATH '$.takeaways',
                    shifts      NUMBER        PATH '$.shifts',
                    toi         VARCHAR2(10)  PATH '$.toi',
                    faceoff_pct NUMBER        PATH '$.faceoffWinningPctg'
                )) jt
            WHERE (p_wm IS NULL OR bngd.loaded_at > p_wm) AND jt.player_id IS NOT NULL
            UNION ALL
            -- Away forwards
            SELECT bngd.game_id,
                   JSON_VALUE(bngd.boxscore_json, '$.awayTeam.abbrev') AS team_abbrev,
                   'A',
                   jt.player_id,
                   CASE WHEN INSTR(jt.player_name, ' ') > 0
                        THEN SUBSTR(jt.player_name, 1, INSTR(jt.player_name, ' ', -1) - 1)
                        ELSE NULL END AS first_name,
                   CASE WHEN INSTR(jt.player_name, ' ') > 0
                        THEN SUBSTR(jt.player_name, INSTR(jt.player_name, ' ', -1) + 1)
                        ELSE jt.player_name END AS last_name,
                   jt.position, jt.sweater_no,
                   jt.goals, jt.assists, jt.points, jt.plus_minus, jt.pim, jt.hits,
                   jt.pp_goals, jt.shots, jt.blocked, jt.giveaways, jt.takeaways,
                   jt.shifts, jt.toi, jt.faceoff_pct
            FROM   bronze_schema.bronze_nhl_game_detail bngd
            CROSS JOIN JSON_TABLE(bngd.boxscore_json,
                '$.playerByGameStats.awayTeam.forwards[*]' COLUMNS (
                    player_id   NUMBER        PATH '$.playerId',
                    player_name VARCHAR2(155) PATH '$.name.default',
                    position    VARCHAR2(5)   PATH '$.position',
                    sweater_no  NUMBER        PATH '$.sweaterNumber',
                    goals       NUMBER        PATH '$.goals',
                    assists     NUMBER        PATH '$.assists',
                    points      NUMBER        PATH '$.points',
                    plus_minus  NUMBER        PATH '$.plusMinus',
                    pim         NUMBER        PATH '$.pim',
                    hits        NUMBER        PATH '$.hits',
                    pp_goals    NUMBER        PATH '$.powerPlayGoals',
                    shots       NUMBER        PATH '$.shots',
                    blocked     NUMBER        PATH '$.blockedAttempts',
                    giveaways   NUMBER        PATH '$.giveaways',
                    takeaways   NUMBER        PATH '$.takeaways',
                    shifts      NUMBER        PATH '$.shifts',
                    toi         VARCHAR2(10)  PATH '$.toi',
                    faceoff_pct NUMBER        PATH '$.faceoffWinningPctg'
                )) jt
            WHERE (p_wm IS NULL OR bngd.loaded_at > p_wm) AND jt.player_id IS NOT NULL
            UNION ALL
            -- Away defense
            SELECT bngd.game_id,
                   JSON_VALUE(bngd.boxscore_json, '$.awayTeam.abbrev') AS team_abbrev,
                   'A',
                   jt.player_id,
                   CASE WHEN INSTR(jt.player_name, ' ') > 0
                        THEN SUBSTR(jt.player_name, 1, INSTR(jt.player_name, ' ', -1) - 1)
                        ELSE NULL END AS first_name,
                   CASE WHEN INSTR(jt.player_name, ' ') > 0
                        THEN SUBSTR(jt.player_name, INSTR(jt.player_name, ' ', -1) + 1)
                        ELSE jt.player_name END AS last_name,
                   jt.position, jt.sweater_no,
                   jt.goals, jt.assists, jt.points, jt.plus_minus, jt.pim, jt.hits,
                   jt.pp_goals, jt.shots, jt.blocked, jt.giveaways, jt.takeaways,
                   jt.shifts, jt.toi, jt.faceoff_pct
            FROM   bronze_schema.bronze_nhl_game_detail bngd
            CROSS JOIN JSON_TABLE(bngd.boxscore_json,
                '$.playerByGameStats.awayTeam.defense[*]' COLUMNS (
                    player_id   NUMBER        PATH '$.playerId',
                    player_name VARCHAR2(155) PATH '$.name.default',
                    position    VARCHAR2(5)   PATH '$.position',
                    sweater_no  NUMBER        PATH '$.sweaterNumber',
                    goals       NUMBER        PATH '$.goals',
                    assists     NUMBER        PATH '$.assists',
                    points      NUMBER        PATH '$.points',
                    plus_minus  NUMBER        PATH '$.plusMinus',
                    pim         NUMBER        PATH '$.pim',
                    hits        NUMBER        PATH '$.hits',
                    pp_goals    NUMBER        PATH '$.powerPlayGoals',
                    shots       NUMBER        PATH '$.shots',
                    blocked     NUMBER        PATH '$.blockedAttempts',
                    giveaways   NUMBER        PATH '$.giveaways',
                    takeaways   NUMBER        PATH '$.takeaways',
                    shifts      NUMBER        PATH '$.shifts',
                    toi         VARCHAR2(10)  PATH '$.toi',
                    faceoff_pct NUMBER        PATH '$.faceoffWinningPctg'
                )) jt
            WHERE (p_wm IS NULL OR bngd.loaded_at > p_wm) AND jt.player_id IS NOT NULL
        )
        WHERE EXISTS (SELECT 1 FROM silver_games sg WHERE sg.game_id = game_id)
    ) src
    ON (ss.game_id = src.game_id AND ss.player_id = src.player_id)
    WHEN NOT MATCHED THEN INSERT (
        game_id, player_id, team_abbrev, home_away, position, sweater_no,
        goals, assists, points, plus_minus, pim, hits,
        power_play_goals, shots_on_goal, blocked_shots,
        giveaways, takeaways, shifts, toi, faceoff_win_pct
    ) VALUES (
        src.game_id, src.player_id, src.team_abbrev, src.home_away, src.position, src.sweater_no,
        NVL(src.goals,0), NVL(src.assists,0), NVL(src.points,0),
        NVL(src.plus_minus,0), NVL(src.pim,0), NVL(src.hits,0),
        NVL(src.pp_goals,0), NVL(src.shots,0), NVL(src.blocked,0),
        NVL(src.giveaways,0), NVL(src.takeaways,0), NVL(src.shifts,0),
        src.toi, src.faceoff_pct
    )
    WHEN MATCHED THEN UPDATE SET
        ss.goals            = NVL(src.goals,0),
        ss.assists          = NVL(src.assists,0),
        ss.points           = NVL(src.points,0),
        ss.plus_minus       = NVL(src.plus_minus,0),
        ss.toi              = src.toi,
        ss.updated_at       = SYSTIMESTAMP;

    v_rows := SQL%ROWCOUNT;
    silver_log('silver_skater_stats', v_rows, v_rows, 0, 'SUCCESS');
    COMMIT;
EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        silver_log('silver_skater_stats', 0, 0, 0, 'ERROR', SUBSTR(SQLERRM, 1, 4000));
        RAISE;
END sp_load_skater_stats;
/


-- ── 7. sp_load_goalie_stats ───────────────────────────────────
-- Source : bronze_schema.bronze_nhl_game_detail → boxscore_json.playerByGameStats.*Team.goalies[*]
-- Target : silver_goalie_stats
-- Note   : $.starter may be integer (1/0) or boolean; mapped to 'Y'/'N'.
--          ES/PP/SH split paths: verify against actual bronze if NULL values appear.
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE PROCEDURE sp_load_goalie_stats (p_wm IN TIMESTAMP DEFAULT NULL) AS
    v_rows  NUMBER;
BEGIN
    MERGE INTO silver_goalie_stats gg
    USING (
        SELECT game_id, team_abbrev, home_away, player_id, sweater_no,
               toi, shots_against, saves, goals_against,
               es_shots, es_goals, pp_shots, pp_goals_ag, sh_shots, sh_goals,
               pim, starter_raw
        FROM (
            -- Home goalies
            SELECT bngd.game_id,
                   JSON_VALUE(bngd.boxscore_json, '$.homeTeam.abbrev') AS team_abbrev,
                   'H'   AS home_away,
                   jt.player_id, jt.sweater_no,
                   jt.toi, jt.shots_against, jt.saves, jt.goals_against,
                   jt.es_shots, jt.es_goals, jt.pp_shots, jt.pp_goals_ag,
                   jt.sh_shots, jt.sh_goals, jt.pim, jt.starter_raw
            FROM   bronze_schema.bronze_nhl_game_detail bngd
            CROSS JOIN JSON_TABLE(bngd.boxscore_json,
                '$.playerByGameStats.homeTeam.goalies[*]' COLUMNS (
                    player_id     NUMBER       PATH '$.playerId',
                    sweater_no    NUMBER       PATH '$.sweaterNumber',
                    toi           VARCHAR2(10) PATH '$.toi',
                    shots_against NUMBER       PATH '$.shotsAgainst',
                    saves         NUMBER       PATH '$.saves',
                    goals_against NUMBER       PATH '$.goalsAgainst',
                    es_shots      NUMBER       PATH '$.evenStrengthShotsAgainst',
                    es_goals      NUMBER       PATH '$.evenStrengthGoalsAgainst',
                    pp_shots      NUMBER       PATH '$.powerPlayShotsAgainst',
                    pp_goals_ag   NUMBER       PATH '$.powerPlayGoalsAgainst',
                    sh_shots      NUMBER       PATH '$.shorthandedShotsAgainst',
                    sh_goals      NUMBER       PATH '$.shorthandedGoalsAgainst',
                    pim           NUMBER       PATH '$.pim',
                    starter_raw   NUMBER       PATH '$.starter'
                )) jt
            WHERE (p_wm IS NULL OR bngd.loaded_at > p_wm) AND jt.player_id IS NOT NULL
            UNION ALL
            -- Away goalies
            SELECT bngd.game_id,
                   JSON_VALUE(bngd.boxscore_json, '$.awayTeam.abbrev') AS team_abbrev,
                   'A',
                   jt.player_id, jt.sweater_no,
                   jt.toi, jt.shots_against, jt.saves, jt.goals_against,
                   jt.es_shots, jt.es_goals, jt.pp_shots, jt.pp_goals_ag,
                   jt.sh_shots, jt.sh_goals, jt.pim, jt.starter_raw
            FROM   bronze_schema.bronze_nhl_game_detail bngd
            CROSS JOIN JSON_TABLE(bngd.boxscore_json,
                '$.playerByGameStats.awayTeam.goalies[*]' COLUMNS (
                    player_id     NUMBER       PATH '$.playerId',
                    sweater_no    NUMBER       PATH '$.sweaterNumber',
                    toi           VARCHAR2(10) PATH '$.toi',
                    shots_against NUMBER       PATH '$.shotsAgainst',
                    saves         NUMBER       PATH '$.saves',
                    goals_against NUMBER       PATH '$.goalsAgainst',
                    es_shots      NUMBER       PATH '$.evenStrengthShotsAgainst',
                    es_goals      NUMBER       PATH '$.evenStrengthGoalsAgainst',
                    pp_shots      NUMBER       PATH '$.powerPlayShotsAgainst',
                    pp_goals_ag   NUMBER       PATH '$.powerPlayGoalsAgainst',
                    sh_shots      NUMBER       PATH '$.shorthandedShotsAgainst',
                    sh_goals      NUMBER       PATH '$.shorthandedGoalsAgainst',
                    pim           NUMBER       PATH '$.pim',
                    starter_raw   NUMBER       PATH '$.starter'
                )) jt
            WHERE (p_wm IS NULL OR bngd.loaded_at > p_wm) AND jt.player_id IS NOT NULL
        )
        WHERE EXISTS (SELECT 1 FROM silver_games sg WHERE sg.game_id = game_id)
    ) src
    ON (gg.game_id = src.game_id AND gg.player_id = src.player_id)
    WHEN NOT MATCHED THEN INSERT (
        game_id, player_id, team_abbrev, home_away, sweater_no,
        toi, shots_against, saves, goals_against,
        es_shots_against, es_goals_against,
        pp_shots_against, pp_goals_against,
        sh_shots_against, sh_goals_against,
        pim, starter
    ) VALUES (
        src.game_id, src.player_id, src.team_abbrev, src.home_away, src.sweater_no,
        src.toi,
        NVL(src.shots_against,0), NVL(src.saves,0), NVL(src.goals_against,0),
        NVL(src.es_shots,0), NVL(src.es_goals,0),
        NVL(src.pp_shots,0), NVL(src.pp_goals_ag,0),
        NVL(src.sh_shots,0), NVL(src.sh_goals,0),
        NVL(src.pim,0),
        CASE WHEN src.starter_raw = 1 THEN 'Y' ELSE 'N' END
    )
    WHEN MATCHED THEN UPDATE SET
        gg.saves         = NVL(src.saves,0),
        gg.goals_against = NVL(src.goals_against,0),
        gg.toi           = src.toi,
        gg.updated_at    = SYSTIMESTAMP;

    v_rows := SQL%ROWCOUNT;
    silver_log('silver_goalie_stats', v_rows, v_rows, 0, 'SUCCESS');
    COMMIT;
EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        silver_log('silver_goalie_stats', 0, 0, 0, 'ERROR', SUBSTR(SQLERRM, 1, 4000));
        RAISE;
END sp_load_goalie_stats;
/


-- ── 8. sp_load_espn_meta ──────────────────────────────────────
-- Source : bronze_schema.bronze_espn_daily → raw_response.events[*]
-- Target : silver_espn_game_meta
-- Note   : ESPN uses competitor[0/1] arrays; home/away determined by $.homeAway field.
--          nhl_game_id resolved by matching silver_games on game_date + team abbreviation.
--          ESPN abbreviations may differ from NHL (e.g. "WSH" vs "WSH" — usually match).
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE PROCEDURE sp_load_espn_meta (p_wm IN TIMESTAMP DEFAULT NULL) AS
    v_rows  NUMBER;
BEGIN
    MERGE INTO silver_espn_game_meta em
    USING (
        SELECT
            -- Resolve NHL game ID by matching on date + home team abbreviation
            (SELECT sg.game_id
             FROM   silver_games sg
             WHERE  sg.game_date = TRUNC(src_inner.event_date)
               AND  (sg.home_team = src_inner.home_abbrev OR sg.away_team = src_inner.home_abbrev)
             FETCH FIRST 1 ROW ONLY)             AS nhl_game_id,
            src_inner.event_date                 AS game_date,
            src_inner.espn_game_id,
            src_inner.home_abbrev                AS home_team_abbrev,
            src_inner.away_abbrev                AS away_team_abbrev,
            src_inner.home_score,
            src_inner.away_score,
            src_inner.venue_name,
            src_inner.venue_city,
            src_inner.attendance,
            src_inner.game_status,
            src_inner.period,
            src_inner.broadcast,
            src_inner.headline,
            src_inner.short_headline
        FROM (
            SELECT
                TO_DATE(SUBSTR(jt.game_date_s, 1, 10), 'YYYY-MM-DD')   AS event_date,
                jt.espn_game_id,
                jt.venue_name,
                jt.venue_city,
                jt.attendance,
                jt.game_status,
                jt.period,
                jt.broadcast,
                jt.headline,
                jt.short_headline,
                -- Derive home/away from competitor positions
                CASE WHEN jt.c0_homeaway = 'home' THEN jt.c0_abbrev ELSE jt.c1_abbrev END  AS home_abbrev,
                CASE WHEN jt.c0_homeaway = 'away' THEN jt.c0_abbrev ELSE jt.c1_abbrev END  AS away_abbrev,
                CASE WHEN jt.c0_homeaway = 'home' THEN jt.c0_score  ELSE jt.c1_score  END  AS home_score,
                CASE WHEN jt.c0_homeaway = 'away' THEN jt.c0_score  ELSE jt.c1_score  END  AS away_score
            FROM   bronze_schema.bronze_espn_daily bed
            CROSS JOIN JSON_TABLE(bed.raw_response, '$.events[*]' COLUMNS (
                espn_game_id    VARCHAR2(20)   PATH '$.id',
                game_date_s     VARCHAR2(30)   PATH '$.date',
                venue_name      VARCHAR2(200)  PATH '$.competitions[0].venue.fullName',
                venue_city      VARCHAR2(100)  PATH '$.competitions[0].venue.address.city',
                attendance      NUMBER         PATH '$.competitions[0].attendance',
                game_status     VARCHAR2(50)   PATH '$.status.type.description',
                period          NUMBER         PATH '$.status.period',
                broadcast       VARCHAR2(200)  PATH '$.competitions[0].broadcasts[0].names[0]',
                headline        VARCHAR2(4000) PATH '$.competitions[0].headlines[0].description',
                short_headline  VARCHAR2(1000) PATH '$.competitions[0].headlines[0].shortLinkText',
                c0_homeaway     VARCHAR2(5)    PATH '$.competitions[0].competitors[0].homeAway',
                c0_abbrev       VARCHAR2(10)   PATH '$.competitions[0].competitors[0].team.abbreviation',
                c0_score        VARCHAR2(10)   PATH '$.competitions[0].competitors[0].score',
                c1_homeaway     VARCHAR2(5)    PATH '$.competitions[0].competitors[1].homeAway',
                c1_abbrev       VARCHAR2(10)   PATH '$.competitions[0].competitors[1].team.abbreviation',
                c1_score        VARCHAR2(10)   PATH '$.competitions[0].competitors[1].score'
            )) jt
            WHERE  (p_wm IS NULL OR bed.loaded_at > p_wm)
              AND  jt.espn_game_id IS NOT NULL
        ) src_inner
    ) src
    ON (em.espn_game_id = src.espn_game_id)
    WHEN NOT MATCHED THEN INSERT (
        nhl_game_id, game_date, espn_game_id,
        home_team_abbrev, away_team_abbrev, home_score, away_score,
        venue_name, venue_city, attendance, game_status, period,
        broadcast, headline, short_headline
    ) VALUES (
        src.nhl_game_id, src.game_date, src.espn_game_id,
        src.home_team_abbrev, src.away_team_abbrev, src.home_score, src.away_score,
        src.venue_name, src.venue_city, src.attendance, src.game_status, src.period,
        src.broadcast, src.headline, src.short_headline
    )
    WHEN MATCHED THEN UPDATE SET
        em.nhl_game_id   = src.nhl_game_id,
        em.attendance    = src.attendance,
        em.headline      = src.headline,
        em.short_headline = src.short_headline,
        em.updated_at    = SYSTIMESTAMP;

    v_rows := SQL%ROWCOUNT;
    silver_log('silver_espn_game_meta', v_rows, v_rows, 0, 'SUCCESS');
    COMMIT;
EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        silver_log('silver_espn_game_meta', 0, 0, 0, 'ERROR', SUBSTR(SQLERRM, 1, 4000));
        RAISE;
END sp_load_espn_meta;
/


-- ── 9. sp_load_global_games ───────────────────────────────────
-- Source : bronze_schema.bronze_sportdb_daily → raw_response[*]  (top-level array)
-- Target : silver_global_games
-- Note   : raw_response is a JSON array (list of game objects).
--          startTimestamp is a Unix epoch integer → stored as-is in VARCHAR2.
--          Paths derived from SportDB API exploration; verify if NULL values appear.
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE PROCEDURE sp_load_global_games (p_wm IN TIMESTAMP DEFAULT NULL) AS
    v_rows  NUMBER;
BEGIN
    MERGE INTO silver_global_games gg
    USING (
        SELECT
            bsd.game_date,
            jt.event_id,
            jt.tournament_id,
            jt.tournament_name,
            jt.tournament_type,
            jt.home_name,
            jt.away_name,
            jt.home_score,
            jt.away_score,
            jt.home_p1, jt.away_p1,
            jt.home_p2, jt.away_p2,
            jt.home_p3, jt.away_p3,
            jt.event_stage,
            jt.winner,
            TO_CHAR(jt.start_ts)   AS start_utc
        FROM   bronze_schema.bronze_sportdb_daily bsd
        CROSS JOIN JSON_TABLE(bsd.raw_response, '$[*]' COLUMNS (
            event_id        VARCHAR2(20)  PATH '$.id',
            tournament_id   VARCHAR2(20)  PATH '$.tournament.id',
            tournament_name VARCHAR2(300) PATH '$.tournament.name',
            tournament_type VARCHAR2(20)  PATH '$.tournament.type',
            home_name       VARCHAR2(200) PATH '$.homeTeam.name',
            away_name       VARCHAR2(200) PATH '$.awayTeam.name',
            home_score      VARCHAR2(10)  PATH '$.homeScore.current',
            away_score      VARCHAR2(10)  PATH '$.awayScore.current',
            home_p1         VARCHAR2(10)  PATH '$.homeScore.period1',
            away_p1         VARCHAR2(10)  PATH '$.awayScore.period1',
            home_p2         VARCHAR2(10)  PATH '$.homeScore.period2',
            away_p2         VARCHAR2(10)  PATH '$.awayScore.period2',
            home_p3         VARCHAR2(10)  PATH '$.homeScore.period3',
            away_p3         VARCHAR2(10)  PATH '$.awayScore.period3',
            event_stage     VARCHAR2(50)  PATH '$.tournament.stage.name',
            winner          VARCHAR2(5)   PATH '$.winner',
            start_ts        NUMBER        PATH '$.startTimestamp'
        )) jt
        WHERE  (p_wm IS NULL OR bsd.loaded_at > p_wm)
          AND  jt.event_id IS NOT NULL
    ) src
    ON (gg.event_id = src.event_id)
    WHEN NOT MATCHED THEN INSERT (
        game_date, event_id, tournament_id, tournament_name, tournament_type,
        home_name, away_name, home_score, away_score,
        home_p1, away_p1, home_p2, away_p2, home_p3, away_p3,
        event_stage, winner, start_utc
    ) VALUES (
        src.game_date, src.event_id, src.tournament_id, src.tournament_name, src.tournament_type,
        src.home_name, src.away_name, src.home_score, src.away_score,
        src.home_p1, src.away_p1, src.home_p2, src.away_p2, src.home_p3, src.away_p3,
        src.event_stage, src.winner, src.start_utc
    )
    WHEN MATCHED THEN UPDATE SET
        gg.home_score = src.home_score,
        gg.away_score = src.away_score,
        gg.winner     = src.winner,
        gg.updated_at = SYSTIMESTAMP;

    v_rows := SQL%ROWCOUNT;
    silver_log('silver_global_games', v_rows, v_rows, 0, 'SUCCESS');
    COMMIT;
EXCEPTION
    WHEN OTHERS THEN
        ROLLBACK;
        silver_log('silver_global_games', 0, 0, 0, 'ERROR', SUBSTR(SQLERRM, 1, 4000));
        RAISE;
END sp_load_global_games;
/


-- ── 10. sp_load_silver (MASTER) ───────────────────────────────
-- Reads all 5 bronze watermarks, calls sub-procedures in dependency order,
-- then advances watermarks to the max bronze loaded_at seen in this run.
--
-- Dependency order:
--   games → players → goals → penalties → three_stars
--          → skater_stats → goalie_stats → espn_meta → global_games
-- ─────────────────────────────────────────────────────────────
CREATE OR REPLACE PROCEDURE sp_load_silver AS
    -- Current watermarks (where we left off last time)
    v_wm_nhl      TIMESTAMP;  -- consolidated for BRONZE_NHL_GAME_DETAIL
    v_wm_espn     TIMESTAMP;
    v_wm_sportdb  TIMESTAMP;
    -- New high watermarks (max bronze loaded_at in this batch)
    v_new_nhl      TIMESTAMP;  -- consolidated for BRONZE_NHL_GAME_DETAIL
    v_new_espn     TIMESTAMP;
    v_new_sportdb  TIMESTAMP;
BEGIN
    -- ── Read current watermarks ──────────────────────────────
    SELECT last_bronze_ts INTO v_wm_nhl
    FROM silver_watermarks WHERE source_table = 'bronze_nhl_game_detail';

    SELECT last_bronze_ts INTO v_wm_espn
    FROM silver_watermarks WHERE source_table = 'bronze_espn_daily';

    SELECT last_bronze_ts INTO v_wm_sportdb
    FROM silver_watermarks WHERE source_table = 'bronze_sportdb_daily';

    -- ── Capture new high-watermarks before running ───────────
    -- (snapshot MAX loaded_at of rows we are about to process)
    SELECT MAX(loaded_at) INTO v_new_nhl
    FROM bronze_schema.bronze_nhl_game_detail
    WHERE (v_wm_nhl IS NULL OR loaded_at > v_wm_nhl);

    SELECT MAX(loaded_at) INTO v_new_espn
    FROM bronze_schema.bronze_espn_daily
    WHERE (v_wm_espn IS NULL OR loaded_at > v_wm_espn);

    SELECT MAX(loaded_at) INTO v_new_sportdb
    FROM bronze_schema.bronze_sportdb_daily
    WHERE (v_wm_sportdb IS NULL OR loaded_at > v_wm_sportdb);

    -- ── Run sub-procedures in dependency order ───────────────
    sp_load_games        (v_wm_nhl);
    sp_load_players      (v_wm_nhl);   -- must precede goals/stars/skater/goalie
    sp_load_goals        (v_wm_nhl);
    sp_load_penalties    (v_wm_nhl);
    sp_load_three_stars  (v_wm_nhl);
    sp_load_skater_stats (v_wm_nhl);
    sp_load_goalie_stats (v_wm_nhl);
    sp_load_espn_meta    (v_wm_espn);       -- needs silver_games populated first
    sp_load_global_games (v_wm_sportdb);

    -- ── Advance watermarks (only when new data was processed) ─
    UPDATE silver_watermarks
    SET    last_bronze_ts  = v_new_nhl,
           last_run_at     = SYSTIMESTAMP,
           rows_processed  = rows_processed + 1
    WHERE  source_table = 'bronze_nhl_game_detail'
      AND  v_new_nhl IS NOT NULL;

    UPDATE silver_watermarks
    SET    last_bronze_ts  = v_new_espn,
           last_run_at     = SYSTIMESTAMP,
           rows_processed  = rows_processed + 1
    WHERE  source_table = 'bronze_espn_daily'
      AND  v_new_espn IS NOT NULL;

    UPDATE silver_watermarks
    SET    last_bronze_ts  = v_new_sportdb,
           last_run_at     = SYSTIMESTAMP,
           rows_processed  = rows_processed + 1
    WHERE  source_table = 'bronze_sportdb_daily'
      AND  v_new_sportdb IS NOT NULL;

    silver_log('sp_load_silver', 0, 0, 0, 'SUCCESS', 'Master run complete');
    COMMIT;
EXCEPTION
    WHEN OTHERS THEN
        -- Watermarks are NOT advanced on failure — next run re-processes the same batch
        ROLLBACK;
        silver_log('sp_load_silver', 0, 0, 0, 'ERROR', SUBSTR(SQLERRM, 1, 4000));
        RAISE;
END sp_load_silver;
/


-- ── Verify compiled procedures ─────────────────────────────────
SELECT object_name, object_type, status
FROM   user_objects
WHERE  object_type = 'PROCEDURE'
ORDER BY object_name;

PROMPT
PROMPT ============================================================
PROMPT Silver Procedures Compiled
PROMPT
PROMPT  sp_load_games         bronze_nhl_score     → silver_games
PROMPT  sp_load_players       bronze_nhl_boxscore  → silver_players
PROMPT  sp_load_goals         bronze_nhl_landing   → silver_goals
PROMPT  sp_load_penalties     bronze_nhl_landing   → silver_penalties
PROMPT  sp_load_three_stars   bronze_nhl_landing   → silver_three_stars
PROMPT  sp_load_skater_stats  bronze_nhl_boxscore  → silver_skater_stats
PROMPT  sp_load_goalie_stats  bronze_nhl_boxscore  → silver_goalie_stats
PROMPT  sp_load_espn_meta     bronze_espn_scoreboard → silver_espn_game_meta
PROMPT  sp_load_global_games  bronze_sportdb_flashscore → silver_global_games
PROMPT  sp_load_silver        master orchestrator
PROMPT
PROMPT  Next: python etl/silver_load.py
PROMPT ============================================================
