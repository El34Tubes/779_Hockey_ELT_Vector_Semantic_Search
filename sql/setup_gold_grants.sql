-- ============================================================
-- Gold Schema Grants - Cross-schema SELECT permissions
-- ============================================================
-- Purpose: Grant gold_schema SELECT access to all silver tables
--          Required before gold ETL procedures can compile
--
-- Usage: Run as SYSTEM user
--   sqlplus system/your_password@FREEPDB1 @sql/setup_gold_grants.sql
-- ============================================================

-- Grant SELECT on all silver data tables to gold_schema
GRANT SELECT ON silver_schema.silver_games           TO gold_schema;
GRANT SELECT ON silver_schema.silver_players         TO gold_schema;
GRANT SELECT ON silver_schema.silver_teams           TO gold_schema;
GRANT SELECT ON silver_schema.silver_goals           TO gold_schema;
GRANT SELECT ON silver_schema.silver_penalties       TO gold_schema;
GRANT SELECT ON silver_schema.silver_three_stars     TO gold_schema;
GRANT SELECT ON silver_schema.silver_skater_stats    TO gold_schema;
GRANT SELECT ON silver_schema.silver_goalie_stats    TO gold_schema;
GRANT SELECT ON silver_schema.silver_espn_game_meta  TO gold_schema;
GRANT SELECT ON silver_schema.silver_global_games    TO gold_schema;

-- Grant SELECT on silver watermarks table (for delta load coordination)
GRANT SELECT ON silver_schema.silver_watermarks      TO gold_schema;

SELECT 'Grants completed: ' || COUNT(*) || ' objects' AS status
FROM dba_tab_privs
WHERE grantee = 'GOLD_SCHEMA'
  AND grantor = 'SILVER_SCHEMA'
  AND privilege = 'SELECT';
