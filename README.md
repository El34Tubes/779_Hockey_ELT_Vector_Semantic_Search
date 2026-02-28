# NHL Semantic Analytics Platform

**Oracle 26ai Vector Search for Hockey Statistics**

A production-ready semantic search platform demonstrating Oracle Database 26ai's native AI capabilities for natural language queries over NHL statistics.

[![Oracle 26ai](https://img.shields.io/badge/Oracle-26ai-F80000?logo=oracle)](https://www.oracle.com/database/)
[![Python 3.9](https://img.shields.io/badge/Python-3.9-3776AB?logo=python)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.50-FF4B4B?logo=streamlit)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 🎯 Project Overview

This project showcases **Oracle 26ai's killer feature**: the ability to combine semantic vector search with traditional SQL filters in a single query, eliminating the need for separate vector databases like Pinecone or Weaviate.

**Key Achievement**: 70% search precision with sub-10ms query times on 9,554 searchable entities.

### Example Query

```python
# Natural language semantic search with SQL filters - ALL IN ONE QUERY
results = engine.search_games(
    query="dominant blowout crushing victory",     # Semantic
    teams=["Colorado Avalanche"],                  # SQL Filter
    min_total_goals=7,                             # SQL Filter
    date_from="2023-01-01",                        # SQL Filter
    overtime_only=True,                            # SQL Filter
    top_k=10
)
```

This **cannot be done** in traditional vector databases without complex pre/post-filtering!

---

## 🏗️ Architecture

### Medallion Data Pipeline

```
┌──────────────────────────────────────────────────────────────┐
│                    NHL API (JSON)                            │
└──────────────────┬───────────────────────────────────────────┘
                   │
         ┌─────────▼─────────┐
         │  BRONZE LAYER     │  Raw JSON storage
         │  4,531 documents  │  • CLOB columns
         │                   │  • Audit trail
         └─────────┬─────────┘
                   │ JSON_TABLE()
         ┌─────────▼─────────┐
         │  SILVER LAYER     │  Normalized relational
         │  195,300 records  │  • PL/SQL ETL
         │                   │  • MERGE upserts
         └─────────┬─────────┘
                   │ Denormalization
         ┌─────────▼─────────┐
         │   GOLD LAYER      │  AI-Ready
         │  9,554 entities   │  • Narratives
         │                   │  • VECTOR(384)
         │                   │  • HNSW indexes
         └───────────────────┘
```

### Oracle 26ai Native Features

- ✅ **VECTOR(384, FLOAT32)** - Native vector storage
- ✅ **VECTOR_DISTANCE()** - Hardware-accelerated similarity
- ✅ **HNSW Indexes** - Sub-10ms approximate nearest neighbor search
- ✅ **Hybrid Queries** - Semantic + SQL filters in one query
- ✅ **JSON_TABLE()** - Declarative JSON parsing
- ✅ **PL/SQL ETL** - Database-native transformations

---

## 🚀 Quick Start

### Prerequisites

- Oracle Database 26ai Free (Docker)
- Python 3.9+
- 2GB RAM minimum

### Installation

1. **Clone repository**
   ```bash
   git clone https://github.com/El34Tubes/779_Hockey_ELT_Vector_Semantic_Search.git
   cd 779_Hockey_ELT_Vector_Semantic_Search
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure database connection**

   Edit `config/db_connect.py` with your Oracle credentials:
   ```python
   DB_CONFIG = {
       'host': 'localhost',
       'port': 55000,
       'service': 'FREEPDB1'
   }
   ```

4. **Run ETL pipeline**
   ```bash
   # View the complete ETL demonstration
   python3 etl/run_complete_etl.py
   ```

5. **Launch web interface**
   ```bash
   streamlit run app.py
   ```

   Open http://localhost:8501 in your browser

---

## 📊 What's Inside

### Data Pipeline

- **Bronze Layer** (4,531 raw JSON docs)
  - NHL API game details
  - Daily scoreboards
  - Audit trail preservation

- **Silver Layer** (195,300 normalized records)
  - 4,100 games
  - 25,551 goals (period-by-period)
  - 1,730 player profiles
  - 147,523 skater seasons
  - 16,396 goalie seasons

- **Gold Layer** (9,554 AI-ready entities)
  - 4,100 game narratives with vectors
  - 5,454 player-season narratives with vectors

### Semantic Narratives

The system generates rich natural language descriptions from raw statistics:

**Raw Data**: Colorado Avalanche 9, Arizona Coyotes 3

**Generated Narrative**:
> "On March 31, 2021, the Arizona Coyotes visited the Colorado Avalanche at Ball Arena. In a dominant one-sided performance, the Colorado Avalanche cruised to a decisive 9-3 blowout victory over the Arizona Coyotes. This offensive shootout featured 12 total goals in a high-scoring affair."

These narratives are embedded using **sentence-transformers/all-MiniLM-L6-v2** (384 dimensions) for semantic search.

---

## 🔍 Features

### 1. Hybrid Search Engine

Combine semantic understanding with precise SQL filters:

```python
from exploration.hybrid_search import HybridSearchEngine

engine = HybridSearchEngine()

# Search games
results = engine.search_games(
    query="offensive high scoring shootout",
    teams=["Colorado Avalanche"],
    min_total_goals=7,
    top_k=10
)

# Search players
results = engine.search_players(
    query="elite scorer offensive force",
    positions=["C"],
    min_points=40,
    top_k=10
)

# Find similar players
results = engine.find_similar_players(
    player_name="McDavid",
    same_position_only=True,
    top_k=10
)
```

### 2. Web Interface

Interactive Streamlit app with three search modes:

- 🏟️ **Game Search** - Find games by narrative + filters (teams, dates, scores)
- 👤 **Player Search** - Find players by style + filters (position, points, games)
- 🔍 **Similar Players** - Discover players with similar playing styles

### 3. Performance

- **Query Speed**: <10ms for pure vector search
- **Hybrid Query**: <15ms with 3+ SQL filters
- **Search Precision**: 70% (up from 30% baseline)
- **Dataset**: 9,554 searchable entities

---

## 📁 Project Structure

```
nhl-semantic-analytics/
├── sql/                          # Database schema and procedures
│   ├── bronze_tables.sql         # Raw data lake
│   ├── silver_tables.sql         # Normalized schema
│   ├── gold_tables.sql           # AI-ready tables
│   ├── silver_procedures.sql     # JSON → Relational ETL
│   ├── gold_procedures.sql       # Silver → Gold ETL
│   └── create_vector_indexes.sql # HNSW indexes
│
├── etl/                          # ETL pipeline
│   ├── generate_narratives_enhanced.py  # Text generation
│   ├── generate_embeddings.py           # Vector embeddings
│   └── run_complete_etl.py              # Full pipeline demo
│
├── exploration/                  # Search engines and demos
│   ├── hybrid_search.py          # Hybrid search engine
│   ├── validate_improvements.py  # Precision testing
│   └── semantic_search_demo.py   # Basic vector search
│
├── config/                       # Configuration
│   └── db_connect.py             # Database connections
│
├── app.py                        # Streamlit web interface
├── requirements.txt              # Python dependencies
│
└── docs/
    ├── ARCHITECTURE.md           # System design details
    ├── TECHNOLOGY_STACK.md       # All technologies used
    ├── TEST_RESULTS.md           # Comprehensive testing
    └── WEB_APP_README.md         # Web interface guide
```

---

## 🎓 Educational Value

This project demonstrates advanced database concepts for **BU 779 Advanced Database Management**:

### 1. **Native AI Integration**
- Vector data types in relational databases
- Hardware-accelerated similarity computation
- Approximate nearest neighbor algorithms (HNSW)

### 2. **Modern ETL Patterns**
- Medallion architecture (Bronze/Silver/Gold)
- Database-native transformations (PL/SQL)
- Idempotent pipelines (MERGE statements)
- JSON parsing without external tools

### 3. **Hybrid Query Optimization**
- Combining vector search with SQL predicates
- Query plan analysis for vector operations
- Index selection for mixed workloads

### 4. **Production Patterns**
- Schema evolution strategies
- Data quality validation
- Performance monitoring
- Scalability considerations

---

## 🔬 Technical Deep Dive

### Why Oracle 26ai?

Traditional approach requires **two separate systems**:

```
❌ OLD WAY:
PostgreSQL (metadata) + Pinecone (vectors)
  ↓
Data sync nightmares
Pre/post filtering complexity
Two databases to secure/backup
Higher infrastructure cost
```

Oracle 26ai enables **unified storage**:

```
✅ NEW WAY:
Oracle 26ai (metadata + vectors)
  ↓
Single source of truth
Native hybrid queries
Unified security/backup
Lower cost
```

### Hybrid Query Example

```sql
SELECT
    game_id,
    home_team_name,
    away_team_name,
    home_score,
    away_score,
    VECTOR_DISTANCE(narrative_vector, :query_vec, COSINE) AS similarity
FROM gold_game_narratives
WHERE
    -- SQL FILTERS (traditional database strength)
    (home_team_name IN ('Colorado Avalanche')
     OR away_team_name IN ('Colorado Avalanche'))
    AND (home_score + away_score) >= 7
    AND game_date >= TO_DATE('2023-01-01', 'YYYY-MM-DD')
    AND overtime_flag = 'Y'
    -- SEMANTIC SIMILARITY (AI capability)
ORDER BY VECTOR_DISTANCE(narrative_vector, :query_vec, COSINE)
FETCH FIRST 10 ROWS ONLY
```

**This is impossible in Pinecone/Weaviate without complex workarounds!**

### HNSW vs IVF Decision

We chose HNSW (Hierarchical Navigable Small World) over IVF (Inverted File):

| Metric | HNSW | IVF |
|--------|------|-----|
| Recall | 95% | 85% |
| Query Latency | <10ms | 20-50ms |
| Build Time | Slower | Faster |
| Maintenance | Automatic | Requires retraining |
| Best For | <1M vectors | >10M vectors |

Our dataset (~10K vectors) is perfect for HNSW.

---

## 📈 Results & Validation

### Search Precision Tests

| Query Type | Precision | Baseline | Improvement |
|------------|-----------|----------|-------------|
| Blowout games | 100% | 20% | +80% |
| Offensive shootouts | 100% | 40% | +60% |
| Defensive battles | 70% | 30% | +40% |
| Elite players | 80% | 40% | +40% |
| **Overall** | **70%** | **30%** | **+40%** |

### Performance Benchmarks

- Pure vector search: 5-10ms
- Hybrid search (3 filters): 10-15ms
- Cold start: ~50ms
- Embedding generation: ~1ms per text
- Narrative generation: ~1ms per entity

See [TEST_RESULTS.md](TEST_RESULTS.md) for detailed validation.

---

## 🛠️ Technology Stack

| Category | Technology | Purpose |
|----------|-----------|---------|
| **Database** | Oracle 26ai Free | Vector + relational storage |
| **Language** | Python 3.9 | ETL, embeddings, application |
| **ML Model** | all-MiniLM-L6-v2 | 384-dim embeddings |
| **Web Framework** | Streamlit 1.50 | Interactive UI |
| **Vector Index** | HNSW | Fast ANN search |
| **ETL** | PL/SQL + Python | Data transformations |
| **API Source** | NHL Stats API | Raw data |

See [TECHNOLOGY_STACK.md](TECHNOLOGY_STACK.md) for complete details.

---

## 📚 Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Complete system design, Oracle features, design decisions
- **[TECHNOLOGY_STACK.md](TECHNOLOGY_STACK.md)** - All 26 technologies used with rationale
- **[TEST_RESULTS.md](TEST_RESULTS.md)** - Comprehensive validation and test results
- **[WEB_APP_README.md](WEB_APP_README.md)** - Web interface user guide

---

## 🎯 Key Takeaways

1. **Oracle 26ai eliminates the need for separate vector databases**
   - Unified storage reduces complexity
   - Native hybrid queries provide better UX
   - Lower infrastructure cost

2. **Database-native processing is underrated**
   - PL/SQL faster than Python for transformations
   - No data egress = better security
   - ACID guarantees for free

3. **Algorithmic narrative generation works**
   - No LLM API costs
   - Deterministic and reproducible
   - Fast enough for real-time

4. **HNSW is optimal for small-medium datasets**
   - Better recall than IVF
   - Lower latency
   - No retraining needed

---

## 🚧 Future Enhancements

- [ ] **RAG (Retrieval-Augmented Generation)** - Use vector search + LLM for Q&A
- [ ] **Real-time updates** - Stream live game data
- [ ] **Multi-modal search** - Add image/video embeddings
- [ ] **Advanced analytics** - Cluster analysis, anomaly detection
- [ ] **Cross-language support** - Multilingual embeddings
- [ ] **Performance optimization** - Table partitioning, materialized views

---

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details

---

## 👨‍🎓 Academic Context

**Course**: BU 779 Advanced Database Management
**Institution**: Boston University
**Semester**: Spring 2026
**Project Type**: Term Project

This project demonstrates advanced database technologies including:
- Native AI capabilities in relational databases
- Vector similarity search at scale
- Modern ETL patterns (medallion architecture)
- Hybrid query optimization
- Production-ready data engineering

---

## 🙏 Acknowledgments

- **Oracle** - For Oracle 26ai Free with native vector capabilities
- **Sentence-Transformers** - For excellent embedding models
- **NHL** - For providing comprehensive statistics API
- **Streamlit** - For rapid web application development

---

## 📞 Contact

For questions about this project:

- **GitHub Issues**: [Create an issue](https://github.com/El34Tubes/779_Hockey_ELT_Vector_Semantic_Search/issues)
- **Documentation**: See docs/ directory for detailed guides

---

## ⭐ Star This Repo

If you find this project helpful for learning about Oracle 26ai vector search or modern data engineering, please give it a star! ⭐

---

*Built with ❤️ for BU 779 Advanced Database Management - Demonstrating Oracle 26ai's native AI capabilities*
