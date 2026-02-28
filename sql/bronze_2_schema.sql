-- ============================================================
-- NHL Semantic Analytics - Bronze Layer Schema v2
-- Redesigned: 1 table per API endpoint, raw JSON only (OSON)
--
-- Design principles:
--   - One table per endpoint hit (no merging two calls into one row)
--   - Raw API response stored verbatim as native Oracle JSON (OSON)
--   - Only identifying metadata columns (no parsed fields)
--   - No processed_flag / workflow state (Silver layer concern)
--   - All JSON columns are native JSON type (OSON binary, not CLOB)
--
-- Sources:
--   1. NHL Official API  (api-web.nhle.com)   -- 3 endpoints
--   2. ESPN NHL API      (site.api.espn.com)  -- 1 endpoint
--   3. SportDB Flashscore (api.sportdb.dev)   -- 1 endpoint
--
-- Run as: bronze_2 user
-- Oracle 23ai / 26ai compatible
-- ============================================================
-- PREREQUISITES (run as SYSTEM):
--   CREATE USER bronze_2 IDENTIFIED BY "Bronze2Schema123";
--   GRANT CONNECT, RESOURCE, UNLIMITED TABLESPACE TO bronze_2;
--   GRANT CREATE VIEW, CREATE PROCEDURE TO bronze_2;
-- ============================================================


-- ── SOURCE 1a: NHL /v1/score/{date} ───────────────────────────
-- One row per calendar date; lightweight game summary list
CREATE TABLE bronze_nhl_score (
    load_id      NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_date    DATE          NOT NULL,
    loaded_at    TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    raw_response JSON          NOT NULL,
    CONSTRAINT uq_nhl_score_date UNIQUE (game_date)
);

CREATE SEARCH INDEX idx_nhl_score_json ON bronze_nhl_score (raw_response) FOR JSON;


-- ── SOURCE 1b: NHL /v1/gamecenter/{gameId}/landing ────────────
-- One row per NHL game; full play-by-play, three stars, team stats
CREATE TABLE bronze_nhl_landing (
    load_id      NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id      NUMBER        NOT NULL,
    game_date    DATE,
    loaded_at    TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    raw_response JSON          NOT NULL,
    CONSTRAINT uq_nhl_landing_game UNIQUE (game_id)
);

CREATE INDEX idx_nhl_landing_date ON bronze_nhl_landing (game_date);
CREATE SEARCH INDEX idx_nhl_landing_json ON bronze_nhl_landing (raw_response) FOR JSON;


-- ── SOURCE 1c: NHL /v1/gamecenter/{gameId}/boxscore ───────────
-- One row per NHL game; per-player skater and goalie stats
CREATE TABLE bronze_nhl_boxscore (
    load_id      NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id      NUMBER        NOT NULL,
    game_date    DATE,
    loaded_at    TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    raw_response JSON          NOT NULL,
    CONSTRAINT uq_nhl_boxscore_game UNIQUE (game_id)
);

CREATE INDEX idx_nhl_boxscore_date ON bronze_nhl_boxscore (game_date);
CREATE SEARCH INDEX idx_nhl_boxscore_json ON bronze_nhl_boxscore (raw_response) FOR JSON;


-- ── SOURCE 2: ESPN /apis/site/v2/sports/hockey/nhl/scoreboard ─
-- One row per calendar date; scores, headlines, venue, attendance
CREATE TABLE bronze_espn_scoreboard (
    load_id      NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_date    DATE          NOT NULL,
    loaded_at    TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    raw_response JSON          NOT NULL,
    CONSTRAINT uq_espn_scoreboard_date UNIQUE (game_date)
);

CREATE SEARCH INDEX idx_espn_scoreboard_json ON bronze_espn_scoreboard (raw_response) FOR JSON;


-- ── SOURCE 3: SportDB /api/flashscore/hockey/live?offset=N ────
-- One row per day offset; global hockey (all leagues worldwide)
CREATE TABLE bronze_sportdb_flashscore (
    load_id      NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_date    DATE          NOT NULL,
    api_offset   NUMBER        DEFAULT 0 NOT NULL,
    loaded_at    TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    raw_response JSON          NOT NULL,
    CONSTRAINT uq_sportdb_flashscore UNIQUE (game_date, api_offset)
);

CREATE SEARCH INDEX idx_sportdb_flashscore_json ON bronze_sportdb_flashscore (raw_response) FOR JSON;


-- ── SHARED: Ingestion audit log ───────────────────────────────
CREATE TABLE bronze_ingestion_log (
    log_id           NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source           VARCHAR2(30)  NOT NULL,  -- NHL_SCORE | NHL_LANDING | NHL_BOXSCORE | ESPN | SPORTDB
    game_date        DATE,
    records_fetched  NUMBER        DEFAULT 0,
    records_inserted NUMBER        DEFAULT 0,
    status           VARCHAR2(20)  NOT NULL,  -- SUCCESS | SKIPPED | EMPTY | ERROR
    message          VARCHAR2(4000),
    logged_at        TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL
);

CREATE INDEX idx_ingest_log ON bronze_ingestion_log (source, game_date);


-- ── PROCEDURES ────────────────────────────────────────────────

CREATE OR REPLACE PROCEDURE bronze_log (
    p_source           IN VARCHAR2,
    p_game_date        IN DATE,
    p_records_fetched  IN NUMBER,
    p_records_inserted IN NUMBER,
    p_status           IN VARCHAR2,
    p_message          IN VARCHAR2 DEFAULT NULL
) AS
BEGIN
    INSERT INTO bronze_ingestion_log (
        source, game_date, records_fetched,
        records_inserted, status, message
    ) VALUES (
        p_source, p_game_date, p_records_fetched,
        p_records_inserted, p_status, p_message
    );
    COMMIT;
END bronze_log;
/


-- ── VERIFY ────────────────────────────────────────────────────
SELECT object_name, object_type, status
FROM user_objects
WHERE object_type IN ('TABLE','INDEX','PROCEDURE')
ORDER BY object_type, object_name;

PROMPT
PROMPT ============================================================
PROMPT Bronze Layer v2 - 1 endpoint per table, native JSON (OSON)
PROMPT
PROMPT  Tables  : bronze_nhl_score       (NHL /v1/score/{date})
PROMPT            bronze_nhl_landing     (NHL /v1/gamecenter/{id}/landing)
PROMPT            bronze_nhl_boxscore    (NHL /v1/gamecenter/{id}/boxscore)
PROMPT            bronze_espn_scoreboard (ESPN scoreboard)
PROMPT            bronze_sportdb_flashscore (SportDB flashscore)
PROMPT            bronze_ingestion_log
PROMPT
PROMPT  Proc    : bronze_log
PROMPT
PROMPT  Next: python etl/daily_load_v2.py --backfill
PROMPT ============================================================
