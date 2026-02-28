-- ============================================================
-- Create HNSW Vector Indexes for Semantic Search
-- ============================================================
-- Purpose: Create Oracle 23ai HNSW (Hierarchical Navigable Small World)
--          indexes on narrative_vector columns for fast similarity search
--
-- HNSW is optimized for high-dimensional vector similarity queries.
-- Alternative: IVF (Inverted File) indexes for larger datasets.
--
-- Usage:
--   sqlplus gold_schema/password@FREEPDB1 @sql/create_vector_indexes.sql
-- ============================================================

-- Game narratives index (4100 vectors × 384 dims)
CREATE VECTOR INDEX idx_game_narratives_vec
ON gold_game_narratives(narrative_vector)
ORGANIZATION NEIGHBOR PARTITIONS
DISTANCE COSINE
WITH TARGET ACCURACY 95;

-- Player season stats index (5454 vectors × 384 dims)
CREATE VECTOR INDEX idx_player_season_vec
ON gold_player_season_stats(narrative_vector)
ORGANIZATION NEIGHBOR PARTITIONS
DISTANCE COSINE
WITH TARGET ACCURACY 95;

-- Team season summary index (191 vectors × 384 dims)
CREATE VECTOR INDEX idx_team_season_vec
ON gold_team_season_summary(narrative_vector)
ORGANIZATION NEIGHBOR PARTITIONS
DISTANCE COSINE
WITH TARGET ACCURACY 95;

-- Check index creation status
SELECT index_name, index_type, status
FROM user_indexes
WHERE index_name LIKE '%VEC%'
ORDER BY index_name;
