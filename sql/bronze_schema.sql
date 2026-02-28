-- ============================================================
-- NHL Semantic Analytics - Bronze Layer Schema
-- Three data sources, raw JSON preserved as-is in native Oracle JSON (OSON binary) format
--
-- Sources:
--   1. NHL Official API  (api-web.nhle.com)   -- primary, historical
--   2. ESPN NHL API      (site.api.espn.com)  -- headlines, narratives
--   3. SportDB Flashscore (api.sportdb.dev)   -- global hockey, daily rolling
--
-- Run as: raw_schema/bronze_schema user
-- Oracle 23ai / 26ai compatible
-- ============================================================
-- PREREQUISITES (run as SYSTEM):
--   CREATE USER bronze_schema IDENTIFIED BY "BronzeSchema123";
--   GRANT CONNECT, RESOURCE, UNLIMITED TABLESPACE TO bronze_schema;
--   GRANT CREATE VIEW, CREATE PROCEDURE, CREATE SEQUENCE TO bronze_schema;
-- ============================================================


-- ── SOURCE 1: NHL Official API ────────────────────────────────
-- /v1/score/{date}  →  one row per calendar date
-- Contains a summary of all games that day (light payload)
-- raw_response stored as native Oracle JSON (OSON binary) for optimal parse performance
CREATE TABLE bronze_nhl_daily (
    load_id         NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_date       DATE          NOT NULL,
    game_count      NUMBER,
    raw_response    JSON          NOT NULL,
    loaded_at       TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    processed_flag  CHAR(1)       DEFAULT 'N' NOT NULL
                                  CHECK (processed_flag IN ('Y','N')),
    processed_at    TIMESTAMP,
    CONSTRAINT uq_nhl_daily_date UNIQUE (game_date)
);

CREATE INDEX idx_nhl_daily_date ON bronze_nhl_daily (game_date);
CREATE SEARCH INDEX idx_nhl_daily_json ON bronze_nhl_daily (raw_response) FOR JSON;


-- /v1/gamecenter/{gameId}/landing  →  one row per NHL game ID
-- Contains: scoring plays, three stars, team stats, venue
-- /v1/gamecenter/{gameId}/boxscore →  merged into same row
-- Contains: per-player stats (18 stats per skater/goalie)
CREATE TABLE bronze_nhl_game_detail (
    load_id         NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id         NUMBER        NOT NULL,
    game_date       DATE,
    season          NUMBER,
    game_type       NUMBER,       -- 1=preseason, 2=regular, 3=playoffs
    home_team       VARCHAR2(10),
    away_team       VARCHAR2(10),
    home_score      NUMBER,
    away_score      NUMBER,
    game_state      VARCHAR2(20),
    landing_json    JSON,
    boxscore_json   JSON,
    loaded_at       TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    processed_flag  CHAR(1)       DEFAULT 'N' NOT NULL
                                  CHECK (processed_flag IN ('Y','N')),
    processed_at    TIMESTAMP,
    CONSTRAINT uq_nhl_game_id UNIQUE (game_id)
);

CREATE INDEX idx_nhl_detail_date   ON bronze_nhl_game_detail (game_date);
CREATE INDEX idx_nhl_detail_season ON bronze_nhl_game_detail (season, game_type);
CREATE SEARCH INDEX idx_nhl_detail_landing  ON bronze_nhl_game_detail (landing_json)  FOR JSON;
CREATE SEARCH INDEX idx_nhl_detail_boxscore ON bronze_nhl_game_detail (boxscore_json) FOR JSON;


-- ── SOURCE 2: ESPN NHL API ────────────────────────────────────
-- /apis/site/v2/sports/hockey/nhl/scoreboard?dates=YYYYMMDD
-- Contains: scores, headlines, game narratives, stars of game
-- One row per calendar date (full response as JSON)
CREATE TABLE bronze_espn_daily (
    load_id         NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_date       DATE          NOT NULL,
    game_count      NUMBER,
    raw_response    JSON          NOT NULL,
    loaded_at       TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    processed_flag  CHAR(1)       DEFAULT 'N' NOT NULL
                                  CHECK (processed_flag IN ('Y','N')),
    processed_at    TIMESTAMP,
    CONSTRAINT uq_espn_daily_date UNIQUE (game_date)
);

CREATE INDEX idx_espn_daily_date ON bronze_espn_daily (game_date);
CREATE SEARCH INDEX idx_espn_daily_json ON bronze_espn_daily (raw_response) FOR JSON;


-- ── SOURCE 3: SportDB Flashscore API ─────────────────────────
-- /api/flashscore/hockey/live?offset=N
-- Global hockey (all leagues worldwide), 7-day rolling window
-- One row per day offset; run daily to build history over time
CREATE TABLE bronze_sportdb_daily (
    load_id         NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_date       DATE          NOT NULL,
    api_offset      NUMBER        DEFAULT 0 NOT NULL,
    game_count      NUMBER,
    raw_response    JSON          NOT NULL,
    loaded_at       TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    processed_flag  CHAR(1)       DEFAULT 'N' NOT NULL
                                  CHECK (processed_flag IN ('Y','N')),
    processed_at    TIMESTAMP,
    CONSTRAINT uq_sportdb_date_offset UNIQUE (game_date, api_offset)
);

CREATE INDEX idx_sportdb_daily_date ON bronze_sportdb_daily (game_date);
CREATE SEARCH INDEX idx_sportdb_daily_json ON bronze_sportdb_daily (raw_response) FOR JSON;


-- ── SHARED: Ingestion audit log ───────────────────────────────
-- Tracks every load attempt across all three sources
CREATE TABLE bronze_ingestion_log (
    log_id          NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source          VARCHAR2(20)  NOT NULL,  -- NHL_DAILY | NHL_DETAIL | ESPN | SPORTDB
    game_date       DATE,
    records_fetched NUMBER        DEFAULT 0,
    records_inserted NUMBER       DEFAULT 0,
    status          VARCHAR2(20)  NOT NULL,  -- SUCCESS | SKIPPED | EMPTY | ERROR
    message         VARCHAR2(4000),
    logged_at       TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL
);

CREATE INDEX idx_ingest_log_source ON bronze_ingestion_log (source, game_date);


-- ── PROCEDURES ────────────────────────────────────────────────

-- Universal log procedure (all sources use this)
CREATE OR REPLACE PROCEDURE bronze_log (
    p_source          IN VARCHAR2,
    p_game_date       IN DATE,
    p_records_fetched IN NUMBER,
    p_records_inserted IN NUMBER,
    p_status          IN VARCHAR2,
    p_message         IN VARCHAR2 DEFAULT NULL
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


-- Mark NHL daily batch processed
CREATE OR REPLACE PROCEDURE bronze_mark_nhl_daily (p_load_id IN NUMBER) AS
BEGIN
    UPDATE bronze_nhl_daily
       SET processed_flag = 'Y', processed_at = SYSTIMESTAMP
     WHERE load_id = p_load_id;
    COMMIT;
END bronze_mark_nhl_daily;
/


-- Mark NHL game detail processed
CREATE OR REPLACE PROCEDURE bronze_mark_nhl_detail (p_game_id IN NUMBER) AS
BEGIN
    UPDATE bronze_nhl_game_detail
       SET processed_flag = 'Y', processed_at = SYSTIMESTAMP
     WHERE game_id = p_game_id;
    COMMIT;
END bronze_mark_nhl_detail;
/


-- Mark ESPN daily batch processed
CREATE OR REPLACE PROCEDURE bronze_mark_espn (p_load_id IN NUMBER) AS
BEGIN
    UPDATE bronze_espn_daily
       SET processed_flag = 'Y', processed_at = SYSTIMESTAMP
     WHERE load_id = p_load_id;
    COMMIT;
END bronze_mark_espn;
/


-- Mark SportDB daily batch processed
CREATE OR REPLACE PROCEDURE bronze_mark_sportdb (p_load_id IN NUMBER) AS
BEGIN
    UPDATE bronze_sportdb_daily
       SET processed_flag = 'Y', processed_at = SYSTIMESTAMP
     WHERE load_id = p_load_id;
    COMMIT;
END bronze_mark_sportdb;
/


-- ── VIEWS ─────────────────────────────────────────────────────

-- NHL daily: one row per game from the daily score response
CREATE OR REPLACE VIEW vw_bronze_nhl_games AS
SELECT
    d.load_id,
    d.game_date,
    d.loaded_at,
    g.*
FROM bronze_nhl_daily d,
    JSON_TABLE(d.raw_response, '$.games[*]'
        COLUMNS (
            game_id             NUMBER        PATH '$.id',
            season              NUMBER        PATH '$.season',
            game_type           NUMBER        PATH '$.gameType',
            game_date_str       VARCHAR2(20)  PATH '$.gameDate',
            start_time_utc      VARCHAR2(30)  PATH '$.startTimeUTC',
            venue               VARCHAR2(200) PATH '$.venue.default',
            venue_location      VARCHAR2(200) PATH '$.venueLocation.default',
            game_state          VARCHAR2(20)  PATH '$.gameState',
            home_team_abbrev    VARCHAR2(10)  PATH '$.homeTeam.abbrev',
            home_team_name      VARCHAR2(100) PATH '$.homeTeam.commonName.default',
            home_score          NUMBER        PATH '$.homeTeam.score',
            home_sog            NUMBER        PATH '$.homeTeam.sog',
            away_team_abbrev    VARCHAR2(10)  PATH '$.awayTeam.abbrev',
            away_team_name      VARCHAR2(100) PATH '$.awayTeam.commonName.default',
            away_score          NUMBER        PATH '$.awayTeam.score',
            away_sog            NUMBER        PATH '$.awayTeam.sog',
            period              NUMBER        PATH '$.period',
            game_outcome        VARCHAR2(20)  PATH '$.gameOutcome.lastPeriodType',
            game_center_link    VARCHAR2(200) PATH '$.gameCenterLink'
        )
    ) g;


-- NHL game detail: three stars per game
CREATE OR REPLACE VIEW vw_bronze_nhl_three_stars AS
SELECT
    d.game_id,
    d.game_date,
    d.home_team,
    d.away_team,
    s.*
FROM bronze_nhl_game_detail d,
    JSON_TABLE(d.landing_json, '$.summary.threeStars[*]'
        COLUMNS (
            star_rank           NUMBER        PATH '$.star',
            player_id           NUMBER        PATH '$.playerId',
            player_name         VARCHAR2(100) PATH '$.name.default',
            team_abbrev         VARCHAR2(10)  PATH '$.teamAbbrev',
            position            VARCHAR2(5)   PATH '$.position',
            goals               NUMBER        PATH '$.goals',
            assists             NUMBER        PATH '$.assists',
            points              NUMBER        PATH '$.points',
            sweater_no          NUMBER        PATH '$.sweaterNo'
        )
    ) s
WHERE d.landing_json IS NOT NULL;


-- NHL game detail: scoring plays
CREATE OR REPLACE VIEW vw_bronze_nhl_goals AS
SELECT
    d.game_id,
    d.game_date,
    d.home_team,
    d.away_team,
    p.period_num,
    g.*
FROM bronze_nhl_game_detail d,
    JSON_TABLE(d.landing_json, '$.summary.scoring[*]'
        COLUMNS (
            period_num      NUMBER  PATH '$.periodDescriptor.number',
            NESTED PATH '$.goals[*]' COLUMNS (
                event_id            NUMBER        PATH '$.eventId',
                scorer_id           NUMBER        PATH '$.playerId',
                scorer_first        VARCHAR2(50)  PATH '$.firstName.default',
                scorer_last         VARCHAR2(50)  PATH '$.lastName.default',
                team_abbrev         VARCHAR2(10)  PATH '$.teamAbbrev.default',
                time_in_period      VARCHAR2(10)  PATH '$.timeInPeriod',
                strength            VARCHAR2(20)  PATH '$.strength',
                shot_type           VARCHAR2(30)  PATH '$.shotType',
                home_score          NUMBER        PATH '$.homeScore',
                away_score          NUMBER        PATH '$.awayScore',
                goals_to_date       NUMBER        PATH '$.goalsToDate',
                highlight_url       VARCHAR2(500) PATH '$.highlightClipSharingUrl'
            )
        )
    ) p, JSON_TABLE(d.landing_json, '$.summary.scoring[*]') g
WHERE d.landing_json IS NOT NULL;


-- ESPN daily: one row per game from the daily response
CREATE OR REPLACE VIEW vw_bronze_espn_games AS
SELECT
    d.load_id,
    d.game_date,
    d.loaded_at,
    g.*
FROM bronze_espn_daily d,
    JSON_TABLE(d.raw_response, '$.events[*]'
        COLUMNS (
            espn_game_id        VARCHAR2(20)  PATH '$.id',
            game_name           VARCHAR2(300) PATH '$.name',
            short_name          VARCHAR2(50)  PATH '$.shortName',
            game_date_str       VARCHAR2(30)  PATH '$.date',
            season_year         NUMBER        PATH '$.season.year',
            season_type         VARCHAR2(30)  PATH '$.season.slug',
            venue_name          VARCHAR2(200) PATH '$.competitions[0].venue.fullName',
            venue_city          VARCHAR2(100) PATH '$.competitions[0].venue.address.city',
            venue_state         VARCHAR2(50)  PATH '$.competitions[0].venue.address.state',
            attendance          NUMBER        PATH '$.competitions[0].attendance',
            game_status         VARCHAR2(50)  PATH '$.competitions[0].status.type.name',
            game_detail         VARCHAR2(50)  PATH '$.competitions[0].status.type.detail',
            period              NUMBER        PATH '$.competitions[0].status.period',
            home_team_name      VARCHAR2(100) PATH '$.competitions[0].competitors[0].team.displayName',
            home_team_abbrev    VARCHAR2(10)  PATH '$.competitions[0].competitors[0].team.abbreviation',
            home_score          VARCHAR2(10)  PATH '$.competitions[0].competitors[0].score',
            away_team_name      VARCHAR2(100) PATH '$.competitions[0].competitors[1].team.displayName',
            away_team_abbrev    VARCHAR2(10)  PATH '$.competitions[0].competitors[1].team.abbreviation',
            away_score          VARCHAR2(10)  PATH '$.competitions[0].competitors[1].score'
        )
    ) g;


-- SportDB daily: one row per game from the daily response
CREATE OR REPLACE VIEW vw_bronze_sportdb_games AS
SELECT
    d.load_id,
    d.game_date,
    d.api_offset,
    d.loaded_at,
    g.*
FROM bronze_sportdb_daily d,
    JSON_TABLE(d.raw_response, '$[*]'
        COLUMNS (
            event_id                VARCHAR2(20)  PATH '$.eventId',
            tournament_id           VARCHAR2(20)  PATH '$.tournamentId',
            tournament_name         VARCHAR2(300) PATH '$.tournamentName',
            home_name               VARCHAR2(200) PATH '$.homeName',
            home_3char              VARCHAR2(5)   PATH '$.home3CharName',
            home_participant_id     VARCHAR2(20)  PATH '$.homeParticipantIds',
            away_name               VARCHAR2(200) PATH '$.awayName',
            away_3char              VARCHAR2(5)   PATH '$.away3CharName',
            away_participant_id     VARCHAR2(20)  PATH '$.awayParticipantIds',
            home_score              VARCHAR2(10)  PATH '$.homeScore',
            away_score              VARCHAR2(10)  PATH '$.awayScore',
            home_score_p1           VARCHAR2(10)  PATH '$.homeResultPeriod1',
            home_score_p2           VARCHAR2(10)  PATH '$.homeResultPeriod2',
            home_score_p3           VARCHAR2(10)  PATH '$.homeResultPeriod3',
            away_score_p1           VARCHAR2(10)  PATH '$.awayResultPeriod1',
            away_score_p2           VARCHAR2(10)  PATH '$.awayResultPeriod2',
            away_score_p3           VARCHAR2(10)  PATH '$.awayResultPeriod3',
            event_stage_id          VARCHAR2(10)  PATH '$.eventStageId',
            event_stage             VARCHAR2(50)  PATH '$.eventStage',
            winner                  VARCHAR2(5)   PATH '$.winner',
            start_date_time_utc     VARCHAR2(50)  PATH '$.startDateTimeUtc',
            start_utime             NUMBER        PATH '$.startUtime',
            tournament_type         VARCHAR2(20)  PATH '$.tournamentType',
            link_details            VARCHAR2(200) PATH '$.links.details',
            link_lineups            VARCHAR2(200) PATH '$.links.lineups',
            link_stats              VARCHAR2(200) PATH '$.links.stats'
        )
    ) g;


-- ── AUDIT VIEW ────────────────────────────────────────────────
CREATE OR REPLACE VIEW vw_bronze_load_summary AS
SELECT
    source,
    game_date,
    records_fetched,
    records_inserted,
    status,
    message,
    logged_at
FROM bronze_ingestion_log
ORDER BY logged_at DESC;


-- ── VERIFY ────────────────────────────────────────────────────
SELECT object_name, object_type, status
FROM user_objects
WHERE object_type IN ('TABLE','INDEX','VIEW','PROCEDURE')
ORDER BY object_type, object_name;

PROMPT
PROMPT ============================================================
PROMPT Bronze Layer - Three Sources Ready
PROMPT
PROMPT  Tables  : bronze_nhl_daily, bronze_nhl_game_detail
PROMPT            bronze_espn_daily, bronze_sportdb_daily
PROMPT            bronze_ingestion_log
PROMPT
PROMPT  Views   : vw_bronze_nhl_games, vw_bronze_nhl_three_stars
PROMPT            vw_bronze_nhl_goals, vw_bronze_espn_games
PROMPT            vw_bronze_sportdb_games, vw_bronze_load_summary
PROMPT
PROMPT  Procs   : bronze_log
PROMPT            bronze_mark_nhl_daily, bronze_mark_nhl_detail
PROMPT            bronze_mark_espn, bronze_mark_sportdb
PROMPT
PROMPT  Next: python etl/daily_load.py --backfill
PROMPT ============================================================
