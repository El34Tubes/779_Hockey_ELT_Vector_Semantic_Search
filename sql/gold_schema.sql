-- ============================================================
-- Gold Schema DDL - NHL Semantic Analytics Platform
-- ============================================================
-- Purpose: Denormalized analytics tables + Oracle VECTOR embeddings
--          for semantic search over game/player narratives and comps
--
-- Architecture:
--   1. Flat/wide tables optimized for analytics queries
--   2. Oracle VECTOR columns for semantic + similarity search
--   3. Native Oracle AI Vector Search (DBMS_VECTOR)
--   4. HNSW indexes for fast nearest-neighbor queries
--
-- Usage:
--   Run as gold_schema user after silver layer is populated
--   sqlplus gold_schema/your_password@FREEPDB1 @sql/gold_schema.sql
-- ============================================================

-- Drop existing objects (clean slate)
BEGIN
    FOR obj IN (SELECT object_name, object_type FROM user_objects
                WHERE object_type IN ('TABLE','VIEW','SEQUENCE','PROCEDURE')) LOOP
        BEGIN
            IF obj.object_type = 'TABLE' THEN
                EXECUTE IMMEDIATE 'DROP TABLE ' || obj.object_name || ' CASCADE CONSTRAINTS PURGE';
            ELSIF obj.object_type = 'PROCEDURE' THEN
                EXECUTE IMMEDIATE 'DROP PROCEDURE ' || obj.object_name;
            ELSIF obj.object_type = 'VIEW' THEN
                EXECUTE IMMEDIATE 'DROP VIEW ' || obj.object_name;
            ELSIF obj.object_type = 'SEQUENCE' THEN
                EXECUTE IMMEDIATE 'DROP SEQUENCE ' || obj.object_name;
            END IF;
        EXCEPTION WHEN OTHERS THEN NULL;
        END;
    END LOOP;
END;
/

-- ============================================================
-- 1. GOLD_GAME_NARRATIVES - Searchable game summaries
-- ============================================================
-- One row per game with full denormalized context + vector embedding
-- for semantic search over game narratives

CREATE TABLE gold_game_narratives (
    game_id             NUMBER          PRIMARY KEY,
    game_date           DATE            NOT NULL,
    season              NUMBER          NOT NULL,
    game_type           NUMBER          NOT NULL,

    -- Teams
    home_team_abbrev    VARCHAR2(10)    NOT NULL,
    home_team_name      VARCHAR2(100),
    away_team_abbrev    VARCHAR2(10)    NOT NULL,
    away_team_name      VARCHAR2(100),

    -- Score
    home_score          NUMBER          NOT NULL,
    away_score          NUMBER          NOT NULL,
    winner              VARCHAR2(10),   -- 'HOME', 'AWAY', 'TIE'
    margin              NUMBER,         -- ABS(home_score - away_score)
    total_goals         NUMBER,         -- home_score + away_score

    -- Game characteristics
    overtime_flag       CHAR(1)         DEFAULT 'N',
    shootout_flag       CHAR(1)         DEFAULT 'N',
    final_period        NUMBER,         -- 3=regulation, 4=OT, 5=2OT, etc

    -- Aggregated stats from game
    total_penalties     NUMBER,
    total_pim           NUMBER,         -- penalty minutes
    home_shots          NUMBER,
    away_shots          NUMBER,
    total_shots         NUMBER,

    -- Three stars (comma-separated for easy display)
    star1_name          VARCHAR2(100),
    star1_team          VARCHAR2(10),
    star2_name          VARCHAR2(100),
    star2_team          VARCHAR2(10),
    star3_name          VARCHAR2(100),
    star3_team          VARCHAR2(10),

    -- Narrative text (generated from stats, used for embedding)
    narrative_text      CLOB            NOT NULL,

    -- Oracle VECTOR embedding of narrative_text
    -- Dimension 384 for all-MiniLM-L6-v2 equivalent Oracle model
    narrative_vector    VECTOR(384, FLOAT32),

    -- Metadata
    loaded_at           TIMESTAMP       DEFAULT SYSTIMESTAMP NOT NULL,
    updated_at          TIMESTAMP       DEFAULT SYSTIMESTAMP NOT NULL
);

CREATE INDEX idx_game_narratives_date    ON gold_game_narratives(game_date);
CREATE INDEX idx_game_narratives_season  ON gold_game_narratives(season);
CREATE INDEX idx_game_narratives_home    ON gold_game_narratives(home_team_abbrev);
CREATE INDEX idx_game_narratives_away    ON gold_game_narratives(away_team_abbrev);

-- HNSW vector index for fast similarity search on narratives
-- CREATE VECTOR INDEX idx_game_narratives_vec ON gold_game_narratives(narrative_vector)
-- ORGANIZATION NEIGHBOR PARTITIONS
-- WITH DISTANCE COSINE
-- PARAMETERS('nof_neighbors=32');
-- (Uncomment after table is populated with vectors)


-- ============================================================
-- 2. GOLD_PLAYER_SEASON_STATS - Player performance by season
-- ============================================================
-- Aggregated player stats per season with narrative + stat vector
-- for both text search and statistical similarity (comps)

CREATE TABLE gold_player_season_stats (
    player_id           NUMBER          NOT NULL,
    season              NUMBER          NOT NULL,

    -- Player info
    full_name           VARCHAR2(155)   NOT NULL,
    position_code       VARCHAR2(10),
    sweater_number      NUMBER,

    -- Games played
    games_played        NUMBER          DEFAULT 0,
    games_as_skater     NUMBER          DEFAULT 0,
    games_as_goalie     NUMBER          DEFAULT 0,

    -- Skater stats (NULL if pure goalie)
    goals               NUMBER,
    assists             NUMBER,
    points              NUMBER,         -- goals + assists
    plus_minus          NUMBER,
    pim                 NUMBER,         -- penalty minutes
    shots               NUMBER,
    shot_pct            NUMBER(5,2),    -- goals/shots * 100
    toi_seconds         NUMBER,         -- total time on ice
    avg_toi_per_game    NUMBER(6,2),    -- seconds per game

    -- Goalie stats (NULL if pure skater)
    saves               NUMBER,
    shots_against       NUMBER,
    goals_against       NUMBER,
    save_pct            NUMBER(5,3),    -- saves/shots_against
    goals_against_avg   NUMBER(4,2),    -- (goals_against * 3600) / toi_seconds
    shutouts            NUMBER,

    -- Situational stats
    pp_goals            NUMBER,         -- power play goals
    sh_goals            NUMBER,         -- short-handed goals
    gw_goals            NUMBER,         -- game-winning goals
    ot_goals            NUMBER,         -- overtime goals

    -- Narrative text (season summary)
    narrative_text      CLOB,
    narrative_vector    VECTOR(384, FLOAT32),

    -- Stat fingerprint vector for player comps (normalized stats)
    -- Skaters: [goals/gp, assists/gp, +/-, shot%, pim/gp, toi/gp]
    -- Goalies: [save%, gaa, shutouts/gp]
    stat_vector         VECTOR(8, FLOAT32),

    -- Metadata
    loaded_at           TIMESTAMP       DEFAULT SYSTIMESTAMP NOT NULL,
    updated_at          TIMESTAMP       DEFAULT SYSTIMESTAMP NOT NULL,

    PRIMARY KEY (player_id, season)
);

CREATE INDEX idx_player_season_name     ON gold_player_season_stats(full_name);
CREATE INDEX idx_player_season_pos      ON gold_player_season_stats(position_code);
CREATE INDEX idx_player_season_pts      ON gold_player_season_stats(points DESC NULLS LAST);
CREATE INDEX idx_player_season_goals    ON gold_player_season_stats(goals DESC NULLS LAST);

-- Vector indexes for player comps (stat_vector) and narrative search
-- CREATE VECTOR INDEX idx_player_stat_vec ON gold_player_season_stats(stat_vector)
-- ORGANIZATION NEIGHBOR PARTITIONS WITH DISTANCE COSINE PARAMETERS('nof_neighbors=16');
-- (Uncomment after population)


-- ============================================================
-- 3. GOLD_TEAM_SEASON_SUMMARY - Team performance by season
-- ============================================================
-- Aggregated team stats for team-level analysis

CREATE TABLE gold_team_season_summary (
    team_abbrev         VARCHAR2(10)    NOT NULL,
    season              NUMBER          NOT NULL,
    team_name           VARCHAR2(100),

    -- Record
    games_played        NUMBER          DEFAULT 0,
    wins                NUMBER          DEFAULT 0,
    losses              NUMBER          DEFAULT 0,
    ot_losses           NUMBER          DEFAULT 0,
    points              NUMBER          DEFAULT 0,  -- 2*wins + ot_losses

    -- Offense
    goals_for           NUMBER          DEFAULT 0,
    goals_per_game      NUMBER(4,2),

    -- Defense
    goals_against       NUMBER          DEFAULT 0,
    goals_against_pg    NUMBER(4,2),

    -- Goal differential
    goal_diff           NUMBER,         -- goals_for - goals_against

    -- Home/Away splits
    home_wins           NUMBER          DEFAULT 0,
    home_losses         NUMBER          DEFAULT 0,
    away_wins           NUMBER          DEFAULT 0,
    away_losses         NUMBER          DEFAULT 0,

    -- Special situations
    blowout_wins        NUMBER          DEFAULT 0,  -- wins by 4+ goals
    comeback_wins       NUMBER          DEFAULT 0,  -- wins when trailing after 2 periods

    -- Narrative
    narrative_text      CLOB,
    narrative_vector    VECTOR(384, FLOAT32),

    -- Metadata
    loaded_at           TIMESTAMP       DEFAULT SYSTIMESTAMP NOT NULL,
    updated_at          TIMESTAMP       DEFAULT SYSTIMESTAMP NOT NULL,

    PRIMARY KEY (team_abbrev, season)
);

CREATE INDEX idx_team_season_pts ON gold_team_season_summary(points DESC);


-- ============================================================
-- 4. GOLD_PLAYER_CAREER_SUMMARY - Career-level player stats
-- ============================================================
-- Roll-up of player_season_stats for career-level search

CREATE TABLE gold_player_career_summary (
    player_id           NUMBER          PRIMARY KEY,
    full_name           VARCHAR2(155)   NOT NULL,
    primary_position    VARCHAR2(10),

    -- Career span
    first_season        NUMBER,
    last_season         NUMBER,
    seasons_played      NUMBER,
    total_games         NUMBER          DEFAULT 0,

    -- Career totals (skater)
    career_goals        NUMBER,
    career_assists      NUMBER,
    career_points       NUMBER,
    career_pim          NUMBER,

    -- Career totals (goalie)
    career_saves        NUMBER,
    career_sa           NUMBER,
    career_ga           NUMBER,
    career_save_pct     NUMBER(5,3),

    -- Career narrative
    narrative_text      CLOB,
    narrative_vector    VECTOR(384, FLOAT32),

    -- Career stat fingerprint (average per-season stats)
    stat_vector         VECTOR(8, FLOAT32),

    loaded_at           TIMESTAMP       DEFAULT SYSTIMESTAMP NOT NULL,
    updated_at          TIMESTAMP       DEFAULT SYSTIMESTAMP NOT NULL
);

CREATE INDEX idx_player_career_name   ON gold_player_career_summary(full_name);
CREATE INDEX idx_player_career_pts    ON gold_player_career_summary(career_points DESC NULLS LAST);


-- ============================================================
-- 5. Support tables and logs
-- ============================================================

-- Watermark tracking for gold ETL
CREATE TABLE gold_watermarks (
    source_table        VARCHAR2(60)    PRIMARY KEY,
    last_silver_ts      TIMESTAMP,
    last_run_at         TIMESTAMP       DEFAULT SYSTIMESTAMP NOT NULL,
    rows_processed      NUMBER          DEFAULT 0
);

-- Seed watermarks for 4 silver source groups
INSERT INTO gold_watermarks (source_table) VALUES ('silver_games');
INSERT INTO gold_watermarks (source_table) VALUES ('silver_players');
INSERT INTO gold_watermarks (source_table) VALUES ('silver_teams');
INSERT INTO gold_watermarks (source_table) VALUES ('silver_skater_stats');
COMMIT;

-- Load log
CREATE TABLE gold_load_log (
    log_id              NUMBER          GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_table        VARCHAR2(60),
    rows_inserted       NUMBER,
    rows_updated        NUMBER,
    rows_skipped        NUMBER,
    vectors_generated   NUMBER,         -- count of embeddings generated
    status              VARCHAR2(20),   -- 'SUCCESS', 'ERROR', 'PARTIAL'
    message             VARCHAR2(4000),
    logged_at           TIMESTAMP       DEFAULT SYSTIMESTAMP NOT NULL
);

CREATE INDEX idx_gold_log_time ON gold_load_log(logged_at DESC);


-- ============================================================
-- 6. Helper procedure for logging
-- ============================================================

CREATE OR REPLACE PROCEDURE gold_log (
    p_table   IN VARCHAR2,
    p_ins     IN NUMBER DEFAULT 0,
    p_upd     IN NUMBER DEFAULT 0,
    p_skip    IN NUMBER DEFAULT 0,
    p_status  IN VARCHAR2,
    p_msg     IN VARCHAR2 DEFAULT NULL,
    p_vectors IN NUMBER DEFAULT 0
) AS
BEGIN
    INSERT INTO gold_load_log (
        source_table, rows_inserted, rows_updated, rows_skipped,
        vectors_generated, status, message
    ) VALUES (
        p_table, p_ins, p_upd, p_skip, p_vectors, p_status, p_msg
    );
    COMMIT;
END gold_log;
/


-- ============================================================
-- Summary
-- ============================================================

SELECT 'Gold schema created: ' || COUNT(*) || ' objects' AS status
FROM user_objects
WHERE object_type IN ('TABLE', 'INDEX', 'PROCEDURE');

SELECT object_type, COUNT(*) AS count
FROM user_objects
GROUP BY object_type
ORDER BY object_type;

-- Check for invalid objects
SELECT object_name, object_type, status
FROM user_objects
WHERE status != 'VALID'
ORDER BY object_type, object_name;
