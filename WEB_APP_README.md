# NHL Semantic Analytics - Web Interface

## Quick Start

### 1. Install Dependencies
```bash
pip install streamlit pandas
```

### 2. Launch the Web App
```bash
streamlit run app.py
```

The app will open automatically in your browser at `http://localhost:8501`

## Features

### 🏟️ Game Search
- **Semantic Search**: Natural language queries like "dramatic overtime thriller"
- **Filters**:
  - Teams (select specific teams)
  - Total goals (min/max range)
  - Goal differential (blowouts)
  - Date range
  - Overtime/Shootout only

**Example Queries:**
- "dominant blowout victory"
- "offensive high scoring shootout"
- "defensive battle low scoring"
- "dramatic comeback overtime"

### 👤 Player Search
- **Semantic Search**: Find players by playing style
- **Filters**:
  - Position (C, L, R, D, G)
  - Points (min/max)
  - Games played (minimum)
  - Seasons (specific years)

**Example Queries:**
- "elite scorer offensive superstar"
- "playmaker assists distributor"
- "physical tough gritty player"

### 🔍 Similar Players
- Find players with similar playing styles
- Uses multi-season vector averaging
- Option to filter by same position

**Example:**
- Find players similar to "McDavid"
- Find players similar to "Hedman"

## Hybrid Search Architecture

The app combines:
1. **Oracle VECTOR_DISTANCE()** - Semantic similarity
2. **SQL WHERE clauses** - Precise filtering
3. **Native performance** - Sub-10ms queries

```sql
-- Example hybrid query
SELECT game_id, home_team, away_team, similarity
FROM gold_game_narratives
WHERE (home_team = 'Colorado Avalanche' OR away_team = 'Colorado Avalanche')
  AND (home_score + away_score) >= 7
  AND narrative_vector IS NOT NULL
ORDER BY VECTOR_DISTANCE(narrative_vector, :query_vec, COSINE)
FETCH FIRST 10 ROWS ONLY;
```

## Demo Tips

1. **Start with pre-filled queries** - Use the suggestion buttons
2. **Adjust filters gradually** - See how results change
3. **Compare searches** - Try same query with/without filters
4. **Show performance** - Queries return in <10ms

## Technical Details

- **Frontend**: Streamlit (Python web framework)
- **Backend**: Oracle 26ai with native VECTOR type
- **Embeddings**: sentence-transformers (all-MiniLM-L6-v2, 384-dim)
- **Data**: 9,745 searchable entities (4,100 games + 5,454 players + 191 teams)
- **Performance**: <10ms query latency

## Troubleshooting

**Issue**: "ModuleNotFoundError: No module named 'streamlit'"
**Solution**: `pip install streamlit pandas`

**Issue**: "Database connection error"
**Solution**: Ensure Oracle container is running: `docker ps`

**Issue**: "No results found"
**Solution**: Remove filters or try a broader query

## Command-Line Demo (Alternative)

If you prefer command-line:
```bash
cd exploration
python hybrid_search.py
```

This runs a demonstration of all hybrid search capabilities.
