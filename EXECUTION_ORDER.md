# NHL Semantic Analytics - Complete Execution Order

## Overview

This document details the **exact order** of all scripts and SQL procedures executed to build the NHL Semantic Analytics Platform from raw data to production-ready semantic search.

---

## 🔄 Complete Pipeline Execution Order

### PHASE 0: Environment Setup (One-Time)

#### 0.1 Database Setup
```bash
# Start Oracle Database 26ai (Docker)
docker start oracle-26ai-free
# OR
docker run -d -p 55000:1521 --name oracle-26ai-free \
  gvenzl/oracle-free:26ai
```

#### 0.2 Schema Creation
Execute in **SQL*Plus or SQL Developer** as SYSTEM/ADMIN user:

```sql
-- File: sql/bronze_schema.sql
-- Creates: bronze_schema user and tables
-- Tables Created:
--   - BRONZE_NHL_GAME_DETAIL
--   - BRONZE_NHL_DAILY
--   - BRONZE_ESPN_DAILY
--   - BRONZE_SPORTDB_DAILY
--   - BRONZE_INGESTION_LOG
```

```sql
-- File: sql/silver_schema.sql
-- Creates: silver_schema user and tables
-- Tables Created:
--   - SILVER_GAMES
--   - SILVER_GOALS
--   - SILVER_PLAYERS
--   - SILVER_SKATER_STATS
--   - SILVER_GOALIE_STATS
--   - SILVER_TEAMS
--   - SILVER_PENALTIES
--   - SILVER_THREE_STARS
--   - SILVER_LOAD_LOG
--   - SILVER_WATERMARKS
```

```sql
-- File: sql/gold_schema.sql
-- Creates: gold_schema user and tables
-- Tables Created:
--   - GOLD_GAME_NARRATIVES (with VECTOR column)
--   - GOLD_PLAYER_SEASON_STATS (with VECTOR column)
--   - GOLD_TEAM_SEASON_SUMMARY (with VECTOR column)
--   - GOLD_PLAYER_CAREER_SUMMARY
--   - GOLD_LOAD_LOG
--   - GOLD_WATERMARKS
```

#### 0.3 Stored Procedure Creation

```sql
-- File: sql/silver_procedures.sql
-- Creates procedures in silver_schema
-- Procedures Created:
--   - sp_load_games
--   - sp_load_goals
--   - sp_load_players
--   - sp_load_skater_stats
--   - sp_load_goalie_stats
--   - sp_load_penalties
--   - sp_load_three_stars
--   - sp_load_espn_meta
--   - sp_load_global_games
--   - sp_load_silver (master procedure)
--   - silver_log (logging utility)
```

```sql
-- File: sql/gold_procedures.sql
-- Creates procedures in gold_schema
-- Procedures Created:
--   - sp_load_game_narratives
--   - sp_load_player_season_stats
--   - sp_load_team_season_summary
--   - gold_log (logging utility)
```

---

### PHASE 1: Bronze Layer - Data Ingestion

**Purpose**: Load raw JSON from NHL API into Oracle CLOB columns

#### 1.1 Historical Game Data Load
```bash
# File: etl/load_nhl_v2.py
# Purpose: Backfill historical game data
# Input: NHL API (game IDs from NHL schedule)
# Output: BRONZE_NHL_GAME_DETAIL table
# Execution:
python3 etl/load_nhl_v2.py

# What it does:
# 1. Fetches game IDs from NHL API schedule
# 2. For each game, calls NHL API game detail endpoint
# 3. Stores full JSON response in BRONZE_NHL_GAME_DETAIL.api_response (CLOB)
# 4. Logs ingestion to BRONZE_INGESTION_LOG
```

**Tables Populated**:
- `BRONZE_NHL_GAME_DETAIL` - Full game JSON (4,089 records)

#### 1.2 Daily Scoreboard Load (Optional - for incremental updates)
```bash
# File: etl/daily_load_v2.py
# Purpose: Load daily scoreboard data
# Input: NHL API daily scoreboard
# Output: BRONZE_NHL_DAILY table
# Execution:
python3 etl/daily_load_v2.py

# What it does:
# 1. Fetches today's scoreboard from NHL API
# 2. Stores JSON response in BRONZE_NHL_DAILY.api_response (CLOB)
# 3. Logs to BRONZE_INGESTION_LOG
```

**Tables Populated**:
- `BRONZE_NHL_DAILY` - Daily scoreboards (442 records)

**Bronze Layer Complete**: 4,531 raw JSON documents stored

---

### PHASE 2: Silver Layer - Relational Transformation

**Purpose**: Parse JSON into normalized relational tables using Oracle JSON_TABLE()

#### 2.1 Master Silver ETL
```bash
# File: etl/silver_load.py
# Purpose: Orchestrate all silver transformations
# Input: Bronze layer tables
# Output: All silver tables
# Execution:
python3 etl/silver_load.py

# What it does:
# Calls these PL/SQL procedures in order:
```

#### 2.2 Individual Silver Procedures (called by silver_load.py)

**Execution Order**:

```sql
-- 2.2.1 Load Games
CALL silver_schema.sp_load_games();
-- Input: BRONZE_NHL_GAME_DETAIL.api_response
-- Output: SILVER_GAMES (4,100 records)
-- Extracts: game_id, game_date, home_team, away_team, scores, venue, etc.
-- Uses: JSON_TABLE() to parse $.gameData and $.liveData

-- 2.2.2 Load Goals
CALL silver_schema.sp_load_goals();
-- Input: BRONZE_NHL_GAME_DETAIL.api_response
-- Output: SILVER_GOALS (25,551 records)
-- Extracts: goal_id, game_id, period, time, scorer, strength (pp/sh/ev)
-- Uses: JSON_TABLE() with nested path $.liveData.plays.allPlays[*]

-- 2.2.3 Load Players
CALL silver_schema.sp_load_players();
-- Input: BRONZE_NHL_GAME_DETAIL.api_response
-- Output: SILVER_PLAYERS (1,730 records)
-- Extracts: player_id, full_name, position, sweater_number
-- Uses: JSON_TABLE() on $.gameData.players[*]

-- 2.2.4 Load Skater Stats
CALL silver_schema.sp_load_skater_stats();
-- Input: BRONZE_NHL_GAME_DETAIL.api_response
-- Output: SILVER_SKATER_STATS (147,523 records)
-- Extracts: player_id, season, games, goals, assists, points, +/-, PIM, shots
-- Uses: JSON_TABLE() on $.gameData.players[*].stats

-- 2.2.5 Load Goalie Stats
CALL silver_schema.sp_load_goalie_stats();
-- Input: BRONZE_NHL_GAME_DETAIL.api_response
-- Output: SILVER_GOALIE_STATS (16,396 records)
-- Extracts: player_id, season, games, wins, losses, GAA, save %
-- Uses: JSON_TABLE() on $.gameData.players[*].stats (goalies only)

-- 2.2.6 Load Penalties (optional)
CALL silver_schema.sp_load_penalties();
-- Input: BRONZE_NHL_GAME_DETAIL.api_response
-- Output: SILVER_PENALTIES
-- Extracts: penalty events, times, types

-- 2.2.7 Load Three Stars (optional)
CALL silver_schema.sp_load_three_stars();
-- Input: BRONZE_NHL_GAME_DETAIL.api_response
-- Output: SILVER_THREE_STARS
-- Extracts: game stars (1st, 2nd, 3rd)
```

**Silver Layer Complete**: 195,300 normalized records across 10 tables

---

### PHASE 3: Gold Layer - Analytics Preparation

**Purpose**: Create denormalized, analytics-ready tables optimized for vector search

#### 3.1 Master Gold ETL
```bash
# File: etl/gold_load.py
# Purpose: Orchestrate gold layer transformations
# Input: Silver layer tables
# Output: Gold layer tables (without vectors yet)
# Execution:
python3 etl/gold_load.py

# What it does:
# Calls these PL/SQL procedures in order:
```

#### 3.2 Individual Gold Procedures (called by gold_load.py)

**Execution Order**:

```sql
-- 3.2.1 Load Game Narratives (structure only, no text yet)
CALL gold_schema.sp_load_game_narratives();
-- Input: SILVER_GAMES, SILVER_GOALS
-- Output: GOLD_GAME_NARRATIVES (4,100 records)
-- Denormalizes: game metadata, scores, dates, teams
-- Columns: game_id, game_date, home_team_name, away_team_name,
--          home_score, away_score, overtime_flag, shootout_flag,
--          narrative_text (NULL), narrative_vector (NULL)

-- 3.2.2 Load Player Season Stats (structure only, no text yet)
CALL gold_schema.sp_load_player_season_stats();
-- Input: SILVER_PLAYERS, SILVER_SKATER_STATS, SILVER_GOALIE_STATS
-- Output: GOLD_PLAYER_SEASON_STATS (5,454 records)
-- Denormalizes: player info + stats for each season
-- Columns: player_id, season, full_name, position_code, games_played,
--          goals, assists, points, plus_minus, pim, shots,
--          narrative_text (NULL), narrative_vector (NULL)

-- 3.2.3 Load Team Season Summary (optional)
CALL gold_schema.sp_load_team_season_summary();
-- Input: SILVER_GAMES, SILVER_TEAMS
-- Output: GOLD_TEAM_SEASON_SUMMARY (191 records)
-- Aggregates: team stats by season
```

**Gold Layer Structure Complete**: 9,745 records ready for narrative generation

---

### PHASE 4: Narrative Generation

**Purpose**: Convert raw statistics into rich natural language descriptions

#### 4.1 Enhanced Narrative Generation
```bash
# File: etl/generate_narratives_enhanced.py
# Purpose: Generate contextual narratives from statistics
# Input: GOLD_GAME_NARRATIVES, GOLD_PLAYER_SEASON_STATS (NULL narratives)
# Output: Same tables with narrative_text populated
# Execution:
python3 etl/generate_narratives_enhanced.py

# What it does:
# 1. For each game in GOLD_GAME_NARRATIVES:
#    a. Fetch game metadata (teams, scores, date, venue)
#    b. Query SILVER_GOALS for period-by-period scoring
#    c. Calculate characteristics (total goals, goal diff, comebacks)
#    d. Generate narrative using generate_enhanced_game_narrative()
#    e. UPDATE gold_game_narratives SET narrative_text = [generated text]
#
# 2. For each player-season in GOLD_PLAYER_SEASON_STATS:
#    a. Fetch player stats (games, goals, assists, +/-, etc.)
#    b. Classify performance level (elite, strong, solid)
#    c. Generate narrative using generate_enhanced_player_narrative()
#    d. UPDATE gold_player_season_stats SET narrative_text = [generated text]
#
# Performance: ~1ms per narrative
# Total time: ~12 seconds for all 9,745 entities
```

**Example Output**:

**Game Narrative**:
> "On March 31, 2021, the Arizona Coyotes visited the Colorado Avalanche at Ball Arena. In a dominant one-sided performance, the Colorado Avalanche cruised to a decisive 9-3 blowout victory over the Arizona Coyotes. This offensive shootout featured 12 total goals in a high-scoring affair."

**Player Narrative**:
> "Connor McDavid, a center, had an elite 2023-24 season, showcasing playmaking ability with 100 assists (pass-first approach) for 132 total points over 76 games (durable workhorse). Defensively responsible with a stellar +34 rating."

**Narratives Complete**: 4,100 game narratives + 5,454 player narratives

---

### PHASE 5: Vector Embedding Generation

**Purpose**: Transform narrative text into 384-dimensional embeddings

#### 5.1 Generate Vector Embeddings
```bash
# File: etl/generate_embeddings.py
# Purpose: Generate sentence embeddings for all narratives
# Input: GOLD tables with narrative_text populated
# Output: Same tables with narrative_vector populated
# Execution:
python3 etl/generate_embeddings.py

# What it does:
# 1. Load sentence-transformers model (all-MiniLM-L6-v2)
#
# 2. For GOLD_GAME_NARRATIVES:
#    a. SELECT game_id, narrative_text WHERE narrative_vector IS NULL
#    b. For each narrative:
#       - embedding = model.encode(narrative_text)  # 384 dimensions
#       - vec_array = array.array('f', embedding)    # Convert to FLOAT32
#       - UPDATE gold_game_narratives
#         SET narrative_vector = :vec_array
#         WHERE game_id = :gid
#    c. Commit in batches of 100
#
# 3. For GOLD_PLAYER_SEASON_STATS:
#    a. SELECT player_id, season, narrative_text WHERE narrative_vector IS NULL
#    b. For each narrative:
#       - embedding = model.encode(narrative_text)  # 384 dimensions
#       - vec_array = array.array('f', embedding)    # Convert to FLOAT32
#       - UPDATE gold_player_season_stats
#         SET narrative_vector = :vec_array
#         WHERE player_id = :pid AND season = :season
#    c. Commit in batches of 100
#
# Performance: ~1ms per embedding
# Total time: ~95 seconds for all 9,745 vectors
# Storage: 9,745 vectors × 384 dims × 4 bytes = ~14 MB
```

**Vector Columns Populated**:
- `GOLD_GAME_NARRATIVES.narrative_vector` - VECTOR(384, FLOAT32) - 4,100 vectors
- `GOLD_PLAYER_SEASON_STATS.narrative_vector` - VECTOR(384, FLOAT32) - 5,454 vectors

**Embeddings Complete**: 9,554 total vectors (4,100 games + 5,454 players)

---

### PHASE 6: Vector Index Creation

**Purpose**: Build HNSW indexes for fast approximate nearest neighbor search

#### 6.1 Create Vector Indexes
Execute in **SQL*Plus or SQL Developer** as gold_schema user:

```sql
-- File: sql/create_vector_indexes.sql
-- Purpose: Create HNSW indexes on vector columns
-- Execution: Run as gold_schema user

-- 6.1.1 Game Narratives Vector Index
CREATE VECTOR INDEX idx_game_narratives_vec
ON gold_game_narratives(narrative_vector)
ORGANIZATION NEIGHBOR PARTITIONS 4
DISTANCE COSINE
WITH TARGET ACCURACY 95;
-- Build time: ~5 seconds
-- Index size: ~1 MB for 4,100 vectors

-- 6.1.2 Player Season Vector Index
CREATE VECTOR INDEX idx_player_season_vec
ON gold_player_season_stats(narrative_vector)
ORGANIZATION NEIGHBOR PARTITIONS 4
DISTANCE COSINE
WITH TARGET ACCURACY 95;
-- Build time: ~5 seconds
-- Index size: ~1.5 MB for 5,454 vectors

-- 6.1.3 Team Season Vector Index (optional)
CREATE VECTOR INDEX idx_team_season_vec
ON gold_team_season_summary(narrative_vector)
ORGANIZATION NEIGHBOR PARTITIONS 4
DISTANCE COSINE
WITH TARGET ACCURACY 95;
-- Build time: ~1 second
-- Index size: ~0.2 MB for 191 vectors
```

**Indexes Created**: 3 HNSW indexes ready for sub-10ms queries

---

### PHASE 7: Validation & Testing

**Purpose**: Verify search quality and performance

#### 7.1 Validate Improvements
```bash
# File: exploration/validate_improvements.py
# Purpose: Test search precision on known queries
# Input: GOLD tables with vectors
# Output: Console output with precision metrics
# Execution:
python3 exploration/validate_improvements.py

# What it does:
# 1. Run targeted test queries:
#    - "dominant one-sided blowout crushing victory" → expect blowouts
#    - "defensive battle goaltending duel low scoring" → expect low-scoring
#    - "offensive shootout high scoring many goals" → expect high-scoring
#    - "elite superstar many points scoring leader" → expect elite players
#
# 2. For each query:
#    - Generate embedding
#    - Query: ORDER BY VECTOR_DISTANCE(...) FETCH FIRST 10 ROWS ONLY
#    - Validate results match expected characteristics
#    - Calculate precision percentage
#
# 3. Output:
#    - Precision scores for each test
#    - Average precision (target: 70%+)
#    - Performance metrics (<10ms queries)
```

**Expected Results**:
- Blowout detection: 100% precision (10/10 games with 4+ goal diff)
- High-scoring games: 100% precision (10/10 games with 7+ goals)
- Elite players: 80% precision (8/10 players with 50+ points)
- **Overall precision: 70%+**

#### 7.2 Hybrid Search Demo
```bash
# File: exploration/hybrid_search.py
# Purpose: Demonstrate hybrid search capabilities
# Input: GOLD tables with vectors
# Output: Console output with search results
# Execution:
python3 exploration/hybrid_search.py

# What it does:
# Runs 5 example searches demonstrating hybrid capabilities:
# 1. High-scoring Colorado games (semantic + team + goals filters)
# 2. Dominant blowouts (semantic + goal differential filter)
# 3. Overtime thrillers (semantic + overtime filter)
# 4. Elite centers (semantic + position + points filters)
# 5. Similar players to McDavid (vector averaging)
```

---

### PHASE 8: Application Layer

**Purpose**: Provide interactive web interface for end users

#### 8.1 Launch Web Interface
```bash
# File: app.py
# Purpose: Streamlit web application for semantic search
# Input: GOLD tables with vectors (via HybridSearchEngine)
# Output: Interactive web interface on http://localhost:8501
# Execution:
streamlit run app.py

# What it does:
# 1. Initialize HybridSearchEngine in session state
# 2. Provide 3 search modes:
#    a. Game Search - semantic query + filters (teams, dates, scores)
#    b. Player Search - semantic query + filters (position, points, games)
#    c. Similar Players - find players with similar styles
# 3. Display results with metrics and expandable details
# 4. Allow real-time filtering and re-querying
```

**Web Interface Running**: http://localhost:8501

---

## 📋 Summary: Complete Execution Sequence

### Initial Setup (One-Time)
1. ✅ Start Oracle Database 26ai (Docker)
2. ✅ Create schemas: `sql/bronze_schema.sql`
3. ✅ Create schemas: `sql/silver_schema.sql`
4. ✅ Create schemas: `sql/gold_schema.sql`
5. ✅ Create procedures: `sql/silver_procedures.sql`
6. ✅ Create procedures: `sql/gold_procedures.sql`

### Bronze Layer (Data Ingestion)
7. ✅ Load historical games: `python3 etl/load_nhl_v2.py`
8. ✅ Load daily scoreboards: `python3 etl/daily_load_v2.py` (optional)

### Silver Layer (Transformation)
9. ✅ Run silver ETL: `python3 etl/silver_load.py`
   - Calls: sp_load_games
   - Calls: sp_load_goals
   - Calls: sp_load_players
   - Calls: sp_load_skater_stats
   - Calls: sp_load_goalie_stats

### Gold Layer (Analytics Prep)
10. ✅ Run gold ETL: `python3 etl/gold_load.py`
    - Calls: sp_load_game_narratives
    - Calls: sp_load_player_season_stats

### AI Layer (Narratives + Vectors)
11. ✅ Generate narratives: `python3 etl/generate_narratives_enhanced.py`
12. ✅ Generate embeddings: `python3 etl/generate_embeddings.py`
13. ✅ Create indexes: `sql/create_vector_indexes.sql`

### Validation
14. ✅ Validate precision: `python3 exploration/validate_improvements.py`
15. ✅ Test hybrid search: `python3 exploration/hybrid_search.py`

### Application
16. ✅ Launch web UI: `streamlit run app.py`

---

## 🔄 Alternative: Run Complete Pipeline

**Single command to demonstrate entire pipeline**:
```bash
# File: etl/run_complete_etl.py
# Purpose: Demonstrate entire pipeline with detailed logging
# NOTE: This assumes data already loaded - it checks status at each phase
python3 etl/run_complete_etl.py
```

---

## 📊 Data Flow Diagram

```
NHL API
   ↓
[load_nhl_v2.py] ────→ BRONZE_NHL_GAME_DETAIL (4,089 JSON docs)
   ↓
[silver_load.py]
   ├─→ sp_load_games ────────→ SILVER_GAMES (4,100 records)
   ├─→ sp_load_goals ────────→ SILVER_GOALS (25,551 records)
   ├─→ sp_load_players ──────→ SILVER_PLAYERS (1,730 records)
   ├─→ sp_load_skater_stats ─→ SILVER_SKATER_STATS (147,523 records)
   └─→ sp_load_goalie_stats ─→ SILVER_GOALIE_STATS (16,396 records)
   ↓
[gold_load.py]
   ├─→ sp_load_game_narratives ──────→ GOLD_GAME_NARRATIVES (4,100 rows)
   └─→ sp_load_player_season_stats ──→ GOLD_PLAYER_SEASON_STATS (5,454 rows)
   ↓
[generate_narratives_enhanced.py] ──→ narrative_text populated
   ↓
[generate_embeddings.py] ───→ narrative_vector populated (VECTOR(384, FLOAT32))
   ↓
[create_vector_indexes.sql] ───→ HNSW indexes built
   ↓
[app.py] ───→ Web interface ready (http://localhost:8501)
```

---

## ⏱️ Estimated Execution Times

| Phase | Script | Time | Records Processed |
|-------|--------|------|-------------------|
| Bronze | load_nhl_v2.py | ~45 min | 4,089 API calls |
| Bronze | daily_load_v2.py | ~1 min | 442 API calls |
| Silver | silver_load.py | ~2 min | 195,300 records |
| Gold | gold_load.py | ~30 sec | 9,745 records |
| Narratives | generate_narratives_enhanced.py | ~12 sec | 9,745 narratives |
| Embeddings | generate_embeddings.py | ~95 sec | 9,554 vectors |
| Indexes | create_vector_indexes.sql | ~11 sec | 3 indexes |
| **TOTAL** | **Full pipeline** | **~50 min** | **9,554 searchable entities** |

---

## 🎯 Key Execution Notes

1. **Idempotency**: All silver/gold procedures use MERGE (upsert), safe to rerun
2. **Incremental Updates**: Can run daily_load_v2.py → silver_load.py → gold_load.py for new data
3. **Dependency Order**: Must follow sequence (can't run gold before silver)
4. **Parallel Execution**: Bronze ingestion scripts can run in parallel (different data sources)
5. **Index Maintenance**: HNSW indexes update automatically, no rebuild needed
6. **Validation**: Always run validate_improvements.py after narrative changes

---

*This execution order is the definitive guide for reproducing the NHL Semantic Analytics Platform.*
