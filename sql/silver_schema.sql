-- ============================================================
-- NHL Semantic Analytics - Silver Layer Schema
-- Structured OLTP tables parsed from Bronze (bronze_2) raw JSON
--
-- Design:
--   - One table per logical entity (games, goals, players, etc.)
--   - Typed, normalized columns — no JSON storage
--   - FK constraints enforce referential integrity within Silver
--   - ESPN → NHL game linkage resolved via nhl_game_id FK
--   - silver_players + silver_teams serve as reference for Gold narratives
--   - All tables are idempotent: UNIQUE constraints prevent re-processing
--
-- Source: bronze_2 schema (native JSON OSON)
-- Target: silver_schema user
-- Oracle 23ai / 26ai compatible
-- ============================================================
-- PREREQUISITES (run as SYSTEM):
--   CREATE USER silver_schema IDENTIFIED BY "SilverSchema123";
--   GRANT CONNECT, RESOURCE, UNLIMITED TABLESPACE TO silver_schema;
--   GRANT CREATE VIEW, CREATE PROCEDURE TO silver_schema;
-- ============================================================


-- ── REFERENCE: Teams ──────────────────────────────────────────
-- Static 32-team NHL reference table
-- ARI → UTA in 2024-25 (Utah Hockey Club); both rows kept for history
CREATE TABLE silver_teams (
    team_abbrev     VARCHAR2(10)  PRIMARY KEY,
    city            VARCHAR2(100) NOT NULL,
    team_name       VARCHAR2(100) NOT NULL,
    full_name       VARCHAR2(210) GENERATED ALWAYS AS (city || ' ' || team_name) VIRTUAL,
    conference      VARCHAR2(15),                    -- Eastern / Western
    division        VARCHAR2(20),                    -- Atlantic / Metro / Central / Pacific
    active_from     NUMBER        DEFAULT 2021,      -- first season in data (YYYYYYYY)
    active_to       NUMBER,                          -- NULL = still active
    loaded_at       TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    updated_at      TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL
);

-- Seed all 32 current NHL teams + Arizona (relocated 2024-25)
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('ANA','Anaheim','Ducks','Western','Pacific');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('BOS','Boston','Bruins','Eastern','Atlantic');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('BUF','Buffalo','Sabres','Eastern','Atlantic');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('CAR','Carolina','Hurricanes','Eastern','Metropolitan');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('CBJ','Columbus','Blue Jackets','Eastern','Metropolitan');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('CGY','Calgary','Flames','Western','Pacific');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('CHI','Chicago','Blackhawks','Western','Central');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('COL','Colorado','Avalanche','Western','Central');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('DAL','Dallas','Stars','Western','Central');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('DET','Detroit','Red Wings','Eastern','Atlantic');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('EDM','Edmonton','Oilers','Western','Pacific');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('FLA','Florida','Panthers','Eastern','Atlantic');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('LAK','Los Angeles','Kings','Western','Pacific');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('MIN','Minnesota','Wild','Western','Central');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('MTL','Montreal','Canadiens','Eastern','Atlantic');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('NJD','New Jersey','Devils','Eastern','Metropolitan');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('NSH','Nashville','Predators','Western','Central');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('NYI','New York','Islanders','Eastern','Metropolitan');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('NYR','New York','Rangers','Eastern','Metropolitan');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('OTT','Ottawa','Senators','Eastern','Atlantic');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('PHI','Philadelphia','Flyers','Eastern','Metropolitan');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('PIT','Pittsburgh','Penguins','Eastern','Metropolitan');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('SEA','Seattle','Kraken','Western','Pacific');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('SJS','San Jose','Sharks','Western','Pacific');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('STL','St. Louis','Blues','Western','Central');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('TBL','Tampa Bay','Lightning','Eastern','Atlantic');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('TOR','Toronto','Maple Leafs','Eastern','Atlantic');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division,active_to) VALUES ('ARI','Arizona','Coyotes','Western','Central',20232024);
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division,active_from) VALUES ('UTA','Utah','Hockey Club','Western','Central',20242025);
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('VAN','Vancouver','Canucks','Western','Pacific');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('VGK','Vegas','Golden Knights','Western','Pacific');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('WPG','Winnipeg','Jets','Western','Central');
INSERT INTO silver_teams (team_abbrev,city,team_name,conference,division) VALUES ('WSH','Washington','Capitals','Eastern','Metropolitan');
COMMIT;


-- ── REFERENCE: Players ────────────────────────────────────────
-- Built incrementally from boxscore player entries during Silver ETL
CREATE TABLE silver_players (
    player_id       NUMBER        PRIMARY KEY,      -- NHL player ID
    first_name      VARCHAR2(50),
    last_name       VARCHAR2(100),
    full_name       VARCHAR2(155) GENERATED ALWAYS AS (first_name || ' ' || last_name) VIRTUAL,
    position        VARCHAR2(5),                    -- C / L / R / D / G
    sweater_no      NUMBER,                         -- most recent observed number
    loaded_at       TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    updated_at      TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL
);

CREATE INDEX idx_silver_player_name ON silver_players (last_name, first_name);


-- ── CORE: Games ───────────────────────────────────────────────
-- One row per NHL game; spine of all Silver fact tables
-- Source: bronze_2.bronze_nhl_score + bronze_2.bronze_nhl_landing
CREATE TABLE silver_games (
    game_id          NUMBER        PRIMARY KEY,     -- NHL game ID
    game_date        DATE          NOT NULL,
    season           NUMBER,                        -- e.g. 20252026
    game_type        NUMBER,                        -- 2=regular, 3=playoffs
    home_team        VARCHAR2(10)  NOT NULL REFERENCES silver_teams (team_abbrev),
    away_team        VARCHAR2(10)  NOT NULL REFERENCES silver_teams (team_abbrev),
    home_score       NUMBER,
    away_score       NUMBER,
    home_sog         NUMBER,
    away_sog         NUMBER,
    last_period_type VARCHAR2(5),                   -- REG / OT / SO
    venue            VARCHAR2(200),
    venue_location   VARCHAR2(200),
    start_time_utc   TIMESTAMP,
    game_state       VARCHAR2(20),
    loaded_at        TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    updated_at       TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL
);

CREATE INDEX idx_silver_games_date   ON silver_games (game_date);
CREATE INDEX idx_silver_games_season ON silver_games (season, game_type);
CREATE INDEX idx_silver_games_home   ON silver_games (home_team, game_date);
CREATE INDEX idx_silver_games_away   ON silver_games (away_team, game_date);


-- ── FACT: Goals ───────────────────────────────────────────────
-- One row per scoring play
-- Source: bronze_2.bronze_nhl_landing → $.summary.scoring[*].goals[*]
CREATE TABLE silver_goals (
    goal_id          NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id          NUMBER        NOT NULL REFERENCES silver_games,
    period           NUMBER,
    time_in_period   VARCHAR2(10),                  -- "MM:SS"
    event_id         NUMBER,
    scorer_id        NUMBER        REFERENCES silver_players (player_id),
    scorer_first     VARCHAR2(50),
    scorer_last      VARCHAR2(100),
    team_abbrev      VARCHAR2(10),
    strength         VARCHAR2(20),                  -- EV / PP / SH
    shot_type        VARCHAR2(30),
    home_score       NUMBER,
    away_score       NUMBER,
    goals_to_date    NUMBER,                        -- scorer's season total at that moment
    assist1_id       NUMBER        REFERENCES silver_players (player_id),
    assist1_first    VARCHAR2(50),
    assist1_last     VARCHAR2(100),
    assist2_id       NUMBER        REFERENCES silver_players (player_id),
    assist2_first    VARCHAR2(50),
    assist2_last     VARCHAR2(100),
    loaded_at        TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    updated_at       TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT uq_goal_event UNIQUE (game_id, event_id)
);

CREATE INDEX idx_silver_goals_game    ON silver_goals (game_id);
CREATE INDEX idx_silver_goals_scorer  ON silver_goals (scorer_id);
CREATE INDEX idx_silver_goals_period  ON silver_goals (game_id, period);


-- ── FACT: Penalties ───────────────────────────────────────────
-- One row per penalty call
-- Source: bronze_2.bronze_nhl_landing → $.summary.penalties[*].penalties[*]
CREATE TABLE silver_penalties (
    penalty_id       NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id          NUMBER        NOT NULL REFERENCES silver_games,
    period           NUMBER,
    time_in_period   VARCHAR2(10),
    team_abbrev      VARCHAR2(10),
    penalized_first  VARCHAR2(50),
    penalized_last   VARCHAR2(100),
    penalized_no     NUMBER,
    drawn_first      VARCHAR2(50),
    drawn_last       VARCHAR2(100),
    drawn_no         NUMBER,
    penalty_type     VARCHAR2(10),                  -- MIN / MAJ / MIS / GM / PS
    duration         NUMBER,                        -- minutes (2, 4, 5, 10)
    desc_key         VARCHAR2(100),                 -- "tripping", "hooking", etc.
    loaded_at        TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    updated_at       TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL
);

CREATE INDEX idx_silver_penalties_game ON silver_penalties (game_id);
CREATE INDEX idx_silver_penalties_team ON silver_penalties (team_abbrev, game_id);


-- ── FACT: Three Stars ─────────────────────────────────────────
-- One row per star award per game (3 rows per game)
-- Source: bronze_2.bronze_nhl_landing → $.summary.threeStars[*]
CREATE TABLE silver_three_stars (
    id               NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id          NUMBER        NOT NULL REFERENCES silver_games,
    star_rank        NUMBER        NOT NULL,        -- 1 / 2 / 3
    player_id        NUMBER        REFERENCES silver_players (player_id),
    player_name      VARCHAR2(100),
    team_abbrev      VARCHAR2(10),
    position         VARCHAR2(5),
    sweater_no       NUMBER,
    goals            NUMBER,
    assists          NUMBER,
    points           NUMBER,
    loaded_at        TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    updated_at       TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT uq_three_stars UNIQUE (game_id, star_rank)
);

CREATE INDEX idx_silver_stars_game   ON silver_three_stars (game_id);
CREATE INDEX idx_silver_stars_player ON silver_three_stars (player_id);


-- ── FACT: Skater Stats ────────────────────────────────────────
-- One row per skater (forward / defenseman) per game
-- Source: bronze_2.bronze_nhl_boxscore → $.playerByGameStats.{home|away}Team.{forwards|defense}[*]
CREATE TABLE silver_skater_stats (
    id               NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id          NUMBER        NOT NULL REFERENCES silver_games,
    player_id        NUMBER        NOT NULL REFERENCES silver_players (player_id),
    team_abbrev      VARCHAR2(10),
    home_away        CHAR(1),                       -- H / A
    position         VARCHAR2(5),
    sweater_no       NUMBER,
    goals            NUMBER        DEFAULT 0,
    assists          NUMBER        DEFAULT 0,
    points           NUMBER        DEFAULT 0,
    plus_minus       NUMBER        DEFAULT 0,
    pim              NUMBER        DEFAULT 0,
    hits             NUMBER        DEFAULT 0,
    power_play_goals NUMBER        DEFAULT 0,
    shots_on_goal    NUMBER        DEFAULT 0,
    blocked_shots    NUMBER        DEFAULT 0,
    giveaways        NUMBER        DEFAULT 0,
    takeaways        NUMBER        DEFAULT 0,
    shifts           NUMBER        DEFAULT 0,
    toi              VARCHAR2(10),                  -- "MM:SS"
    faceoff_win_pct  NUMBER,                        -- 0.0–100.0
    loaded_at        TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    updated_at       TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT uq_skater_game UNIQUE (game_id, player_id)
);

CREATE INDEX idx_silver_skater_game   ON silver_skater_stats (game_id);
CREATE INDEX idx_silver_skater_player ON silver_skater_stats (player_id, game_id);
CREATE INDEX idx_silver_skater_team   ON silver_skater_stats (team_abbrev, game_id);


-- ── FACT: Goalie Stats ────────────────────────────────────────
-- One row per goalie per game
-- Source: bronze_2.bronze_nhl_boxscore → $.playerByGameStats.{home|away}Team.goalies[*]
CREATE TABLE silver_goalie_stats (
    id               NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_id          NUMBER        NOT NULL REFERENCES silver_games,
    player_id        NUMBER        NOT NULL REFERENCES silver_players (player_id),
    team_abbrev      VARCHAR2(10),
    home_away        CHAR(1),                       -- H / A
    sweater_no       NUMBER,
    toi              VARCHAR2(10),                  -- "MM:SS"
    shots_against    NUMBER        DEFAULT 0,
    saves            NUMBER        DEFAULT 0,
    goals_against    NUMBER        DEFAULT 0,
    es_shots_against NUMBER        DEFAULT 0,
    es_goals_against NUMBER        DEFAULT 0,
    pp_shots_against NUMBER        DEFAULT 0,
    pp_goals_against NUMBER        DEFAULT 0,
    sh_shots_against NUMBER        DEFAULT 0,
    sh_goals_against NUMBER        DEFAULT 0,
    pim              NUMBER        DEFAULT 0,
    starter          CHAR(1),                       -- Y / N
    loaded_at        TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    updated_at       TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT uq_goalie_game UNIQUE (game_id, player_id)
);

CREATE INDEX idx_silver_goalie_game   ON silver_goalie_stats (game_id);
CREATE INDEX idx_silver_goalie_player ON silver_goalie_stats (player_id, game_id);


-- ── ENRICHMENT: ESPN Game Metadata ────────────────────────────
-- One row per ESPN game event; joined to silver_games via nhl_game_id
-- nhl_game_id resolved during Silver ETL by matching game_date + team abbrev
-- Source: bronze_2.bronze_espn_scoreboard → $.events[*]
CREATE TABLE silver_espn_game_meta (
    id               NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nhl_game_id      NUMBER        REFERENCES silver_games (game_id),  -- resolved FK
    game_date        DATE          NOT NULL,
    espn_game_id     VARCHAR2(20),
    home_team_abbrev VARCHAR2(10),
    away_team_abbrev VARCHAR2(10),
    home_score       VARCHAR2(10),
    away_score       VARCHAR2(10),
    venue_name       VARCHAR2(200),
    venue_city       VARCHAR2(100),
    attendance       NUMBER,
    game_status      VARCHAR2(50),
    period           NUMBER,
    broadcast        VARCHAR2(200),
    headline         VARCHAR2(4000),                -- competitions[0].headlines[0].description
    short_headline   VARCHAR2(1000),                -- headlines[0].shortLinkText
    loaded_at        TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    updated_at       TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT uq_espn_game UNIQUE (espn_game_id)
);

CREATE INDEX idx_silver_espn_date    ON silver_espn_game_meta (game_date);
CREATE INDEX idx_silver_espn_nhl_id  ON silver_espn_game_meta (nhl_game_id);


-- ── FACT: Global Hockey Games (SportDB) ───────────────────────
-- One row per non-NHL game across all global hockey leagues
-- Source: bronze_2.bronze_sportdb_flashscore → $[*]
-- Note: no player-level data; score and league context only
CREATE TABLE silver_global_games (
    id               NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    game_date        DATE          NOT NULL,
    event_id         VARCHAR2(20),
    tournament_id    VARCHAR2(20),
    tournament_name  VARCHAR2(300),
    tournament_type  VARCHAR2(20),                  -- league / cup / etc.
    home_name        VARCHAR2(200),
    away_name        VARCHAR2(200),
    home_score       VARCHAR2(10),
    away_score       VARCHAR2(10),
    home_p1          VARCHAR2(10),
    away_p1          VARCHAR2(10),
    home_p2          VARCHAR2(10),
    away_p2          VARCHAR2(10),
    home_p3          VARCHAR2(10),
    away_p3          VARCHAR2(10),
    event_stage      VARCHAR2(50),                  -- Regular Season / Playoff
    winner           VARCHAR2(5),                   -- home / away
    start_utc        VARCHAR2(50),
    loaded_at        TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    updated_at       TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    CONSTRAINT uq_global_event UNIQUE (event_id)
);

CREATE INDEX idx_silver_global_date       ON silver_global_games (game_date);
CREATE INDEX idx_silver_global_tournament ON silver_global_games (tournament_id);


-- ── PROCEDURES ────────────────────────────────────────────────

-- Silver audit log
CREATE TABLE silver_load_log (
    log_id           NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_table     VARCHAR2(50)  NOT NULL,        -- which silver table was populated
    games_processed  NUMBER        DEFAULT 0,
    rows_inserted    NUMBER        DEFAULT 0,
    rows_skipped     NUMBER        DEFAULT 0,
    status           VARCHAR2(20)  NOT NULL,
    message          VARCHAR2(4000),
    logged_at        TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL
);

-- ── DELTA LOAD: Watermarks ─────────────────────────────────────
-- Tracks the highest bronze_2.loaded_at processed for each source table.
-- Silver ETL queries: WHERE bronze.loaded_at > last_bronze_ts
-- After each successful run, ETL updates last_bronze_ts + last_run_at.
CREATE TABLE silver_watermarks (
    source_table     VARCHAR2(60)  PRIMARY KEY,     -- bronze_2 table name
    last_bronze_ts   TIMESTAMP,                     -- max bronze loaded_at processed (NULL = never run)
    last_run_at      TIMESTAMP     DEFAULT SYSTIMESTAMP NOT NULL,
    rows_processed   NUMBER        DEFAULT 0
);

-- Seed one row per bronze_2 source table
INSERT INTO silver_watermarks (source_table) VALUES ('bronze_nhl_score');
INSERT INTO silver_watermarks (source_table) VALUES ('bronze_nhl_landing');
INSERT INTO silver_watermarks (source_table) VALUES ('bronze_nhl_boxscore');
INSERT INTO silver_watermarks (source_table) VALUES ('bronze_espn_scoreboard');
INSERT INTO silver_watermarks (source_table) VALUES ('bronze_sportdb_flashscore');
COMMIT;


CREATE OR REPLACE PROCEDURE silver_log (
    p_source_table   IN VARCHAR2,
    p_games          IN NUMBER,
    p_inserted       IN NUMBER,
    p_skipped        IN NUMBER,
    p_status         IN VARCHAR2,
    p_message        IN VARCHAR2 DEFAULT NULL
) AS
BEGIN
    INSERT INTO silver_load_log (source_table, games_processed, rows_inserted,
                                 rows_skipped, status, message)
    VALUES (p_source_table, p_games, p_inserted, p_skipped, p_status, p_message);
    COMMIT;
END silver_log;
/


-- ── VIEWS ─────────────────────────────────────────────────────

-- Complete game result with team full names
CREATE OR REPLACE VIEW vw_silver_game_results AS
SELECT
    g.game_id,
    g.game_date,
    g.season,
    g.game_type,
    ht.full_name                          AS home_team_full,
    g.home_team,
    g.home_score,
    g.home_sog,
    g.away_score,
    g.away_sog,
    at_.full_name                         AS away_team_full,
    g.away_team,
    g.last_period_type,
    g.venue,
    e.attendance,
    e.headline                            AS espn_headline
FROM silver_games g
LEFT JOIN silver_teams  ht  ON ht.team_abbrev = g.home_team
LEFT JOIN silver_teams  at_ ON at_.team_abbrev = g.away_team
LEFT JOIN silver_espn_game_meta e ON e.nhl_game_id = g.game_id;


-- Player game log (skater — all stats in one row)
CREATE OR REPLACE VIEW vw_silver_player_game_log AS
SELECT
    sk.game_id,
    g.game_date,
    g.season,
    p.player_id,
    p.full_name                           AS player_name,
    p.position,
    sk.team_abbrev,
    sk.home_away,
    sk.goals,
    sk.assists,
    sk.points,
    sk.plus_minus,
    sk.shots_on_goal,
    sk.hits,
    sk.blocked_shots,
    sk.toi,
    sk.pim,
    sk.giveaways,
    sk.takeaways,
    sk.faceoff_win_pct
FROM silver_skater_stats sk
JOIN silver_games   g ON g.game_id   = sk.game_id
JOIN silver_players p ON p.player_id = sk.player_id;


-- Three stars with full game context
CREATE OR REPLACE VIEW vw_silver_three_stars AS
SELECT
    ts.game_id,
    g.game_date,
    g.season,
    g.home_team,
    g.home_score,
    g.away_score,
    g.away_team,
    g.last_period_type,
    ts.star_rank,
    ts.player_name,
    ts.team_abbrev,
    ts.position,
    ts.goals,
    ts.assists,
    ts.points
FROM silver_three_stars ts
JOIN silver_games g ON g.game_id = ts.game_id
ORDER BY g.game_date DESC, ts.star_rank;


-- Penalty summary per game
CREATE OR REPLACE VIEW vw_silver_penalty_summary AS
SELECT
    p.game_id,
    g.game_date,
    p.team_abbrev,
    COUNT(*)                              AS total_penalties,
    SUM(p.duration)                       AS total_pim,
    SUM(CASE WHEN p.penalty_type = 'MAJ' THEN 1 ELSE 0 END) AS majors,
    SUM(CASE WHEN p.penalty_type = 'MIS' THEN 1 ELSE 0 END) AS misconducts
FROM silver_penalties p
JOIN silver_games g ON g.game_id = p.game_id
GROUP BY p.game_id, g.game_date, p.team_abbrev;


-- ── VERIFY ────────────────────────────────────────────────────
SELECT object_name, object_type, status
FROM user_objects
WHERE object_type IN ('TABLE','INDEX','VIEW','PROCEDURE')
ORDER BY object_type, object_name;

PROMPT
PROMPT ============================================================
PROMPT Silver Layer Schema Ready
PROMPT
PROMPT  Reference : silver_teams (32 NHL teams seeded)
PROMPT             silver_players (built during ETL)
PROMPT
PROMPT  NHL Facts : silver_games, silver_goals, silver_penalties
PROMPT             silver_three_stars
PROMPT             silver_skater_stats, silver_goalie_stats
PROMPT
PROMPT  Enrichment: silver_espn_game_meta (ESPN headlines + venue)
PROMPT             silver_global_games (KHL/SHL/etc. scores)
PROMPT
PROMPT  Audit     : silver_load_log, silver_log procedure
PROMPT  Delta     : silver_watermarks (per-source high-watermark timestamps)
PROMPT
PROMPT  Views     : vw_silver_game_results, vw_silver_player_game_log
PROMPT             vw_silver_three_stars, vw_silver_penalty_summary
PROMPT
PROMPT  Next: python etl/silver_load.py --backfill
PROMPT ============================================================
