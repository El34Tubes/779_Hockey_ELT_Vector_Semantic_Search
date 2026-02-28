-- ============================================================
-- Silver Layer Cross-Schema Grants
-- Run as SYSTEM (or DBA) before compiling silver_procedures.sql
--
-- silver_schema stored procedures read directly from bronze_2.
-- These grants make bronze_2 tables visible to the silver_schema
-- definer-rights procedures.
-- ============================================================

GRANT SELECT ON bronze_2.bronze_nhl_score          TO silver_schema;
GRANT SELECT ON bronze_2.bronze_nhl_landing        TO silver_schema;
GRANT SELECT ON bronze_2.bronze_nhl_boxscore       TO silver_schema;
GRANT SELECT ON bronze_2.bronze_espn_scoreboard    TO silver_schema;
GRANT SELECT ON bronze_2.bronze_sportdb_flashscore TO silver_schema;

PROMPT
PROMPT Grants applied: silver_schema can now SELECT from all bronze_2 source tables.
PROMPT Next: sqlplus silver_schema/... @sql/silver_procedures.sql
PROMPT
