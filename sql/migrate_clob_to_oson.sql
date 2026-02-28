-- ============================================================
-- Bronze Layer: Migrate CLOB JSON → Native Oracle JSON (OSON)
-- ============================================================
-- Run AFTER the NHL backfill has completed.
-- Run as: bronze_schema user
--
-- What this does:
--   For each table with JSON CLOB columns:
--     1. Drop the SEARCH INDEX (tied to the old CLOB column)
--     2. Add a new native JSON column
--     3. Populate it from the CLOB (Oracle auto-parses to OSON binary)
--     4. Drop old CLOB column
--     5. Rename new JSON column back to original name
--     6. Re-add NOT NULL constraint where required
--     7. Recreate SEARCH INDEX on the native JSON column
--
-- Benefits of native JSON over CLOB:
--   - OSON binary format: more compact, no text parsing on access
--   - Faster JSON_TABLE, JSON_VALUE, JSON_EXISTS queries
--   - python-oracledb passes Python dicts directly (no json.dumps needed)
--   - Better integration with Oracle 23ai/26ai vector and duality features
-- ============================================================


-- ── TABLE 1: bronze_nhl_daily (raw_response) ─────────────────

DROP INDEX idx_nhl_daily_json;

ALTER TABLE bronze_nhl_daily ADD (raw_response_json JSON);

UPDATE /*+ PARALLEL(bronze_nhl_daily, 4) */ bronze_nhl_daily
   SET raw_response_json = raw_response;
COMMIT;

ALTER TABLE bronze_nhl_daily DROP COLUMN raw_response;
ALTER TABLE bronze_nhl_daily RENAME COLUMN raw_response_json TO raw_response;
ALTER TABLE bronze_nhl_daily MODIFY raw_response NOT NULL;

CREATE SEARCH INDEX idx_nhl_daily_json ON bronze_nhl_daily (raw_response) FOR JSON;


-- ── TABLE 2: bronze_nhl_game_detail (landing_json) ───────────

DROP INDEX idx_nhl_detail_landing;

ALTER TABLE bronze_nhl_game_detail ADD (landing_json_new JSON);

UPDATE /*+ PARALLEL(bronze_nhl_game_detail, 4) */ bronze_nhl_game_detail
   SET landing_json_new = landing_json
 WHERE landing_json IS NOT NULL;
COMMIT;

ALTER TABLE bronze_nhl_game_detail DROP COLUMN landing_json;
ALTER TABLE bronze_nhl_game_detail RENAME COLUMN landing_json_new TO landing_json;

CREATE SEARCH INDEX idx_nhl_detail_landing ON bronze_nhl_game_detail (landing_json) FOR JSON;


-- ── TABLE 3: bronze_nhl_game_detail (boxscore_json) ──────────

DROP INDEX idx_nhl_detail_boxscore;

ALTER TABLE bronze_nhl_game_detail ADD (boxscore_json_new JSON);

UPDATE /*+ PARALLEL(bronze_nhl_game_detail, 4) */ bronze_nhl_game_detail
   SET boxscore_json_new = boxscore_json
 WHERE boxscore_json IS NOT NULL;
COMMIT;

ALTER TABLE bronze_nhl_game_detail DROP COLUMN boxscore_json;
ALTER TABLE bronze_nhl_game_detail RENAME COLUMN boxscore_json_new TO boxscore_json;

CREATE SEARCH INDEX idx_nhl_detail_boxscore ON bronze_nhl_game_detail (boxscore_json) FOR JSON;


-- ── TABLE 4: bronze_espn_daily (raw_response) ────────────────

DROP INDEX idx_espn_daily_json;

ALTER TABLE bronze_espn_daily ADD (raw_response_json JSON);

UPDATE /*+ PARALLEL(bronze_espn_daily, 4) */ bronze_espn_daily
   SET raw_response_json = raw_response;
COMMIT;

ALTER TABLE bronze_espn_daily DROP COLUMN raw_response;
ALTER TABLE bronze_espn_daily RENAME COLUMN raw_response_json TO raw_response;
ALTER TABLE bronze_espn_daily MODIFY raw_response NOT NULL;

CREATE SEARCH INDEX idx_espn_daily_json ON bronze_espn_daily (raw_response) FOR JSON;


-- ── TABLE 5: bronze_sportdb_daily (raw_response) ─────────────

DROP INDEX idx_sportdb_daily_json;

ALTER TABLE bronze_sportdb_daily ADD (raw_response_json JSON);

UPDATE bronze_sportdb_daily
   SET raw_response_json = raw_response;
COMMIT;

ALTER TABLE bronze_sportdb_daily DROP COLUMN raw_response;
ALTER TABLE bronze_sportdb_daily RENAME COLUMN raw_response_json TO raw_response;
ALTER TABLE bronze_sportdb_daily MODIFY raw_response NOT NULL;

CREATE SEARCH INDEX idx_sportdb_daily_json ON bronze_sportdb_daily (raw_response) FOR JSON;


-- ── VERIFY ────────────────────────────────────────────────────
-- Confirm column types changed to JSON and row counts are intact

SELECT table_name, column_name, data_type
FROM user_tab_columns
WHERE table_name IN ('BRONZE_NHL_DAILY','BRONZE_NHL_GAME_DETAIL',
                     'BRONZE_ESPN_DAILY','BRONZE_SPORTDB_DAILY')
  AND column_name IN ('RAW_RESPONSE','LANDING_JSON','BOXSCORE_JSON')
ORDER BY table_name, column_name;

SELECT 'bronze_nhl_daily'      AS tbl, COUNT(*) AS rows FROM bronze_nhl_daily      UNION ALL
SELECT 'bronze_nhl_game_detail',         COUNT(*) FROM bronze_nhl_game_detail UNION ALL
SELECT 'bronze_espn_daily',              COUNT(*) FROM bronze_espn_daily      UNION ALL
SELECT 'bronze_sportdb_daily',           COUNT(*) FROM bronze_sportdb_daily;

PROMPT
PROMPT ============================================================
PROMPT OSON Migration Complete - all JSON columns now native type
PROMPT Next: update ETL loaders (remove json.dumps calls)
PROMPT ============================================================
