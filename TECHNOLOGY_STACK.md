# NHL Semantic Analytics - Technology Stack

## Overview

This document lists all technologies, libraries, and tools used in the NHL Semantic Analytics Platform, organized by layer and purpose.

---

## 📊 Database & Storage Layer

### **Oracle Database 26ai (FREEPDB1)**
- **Version**: Oracle Database 26ai Free Release
- **Purpose**: Primary database system providing both relational and AI vector capabilities
- **Key Features Used**:
  - VECTOR data type for embedding storage
  - VECTOR_DISTANCE() function for similarity computation
  - HNSW vector indexes for fast ANN search
  - JSON_TABLE() for parsing API responses
  - PL/SQL stored procedures for ETL
  - MERGE statements for upserts
  - Multi-schema architecture (bronze/silver/gold)
- **Why Chosen**: Only database with native vector + relational capabilities in one system
- **Installation**: Docker container via Oracle Database Free
- **Connection**: localhost:55000

---

## 🐍 Python Ecosystem

### **Python 3.9**
- **Purpose**: Primary programming language for ETL, embeddings, and application
- **Why Chosen**: Rich ecosystem for data processing and ML

### **oracledb (Python Driver)**
- **Version**: Latest (python-oracledb)
- **Purpose**: Oracle database connectivity
- **Usage**:
  - Execute SQL queries
  - Call stored procedures
  - Manage connections and transactions
  - Handle VECTOR data type
- **Why Chosen**: Official Oracle driver with native vector support
- **Import**: `import oracledb`

---

## 🤖 Machine Learning & Embeddings

### **sentence-transformers**
- **Version**: Latest
- **Purpose**: Generate semantic embeddings from text
- **Model Used**: `sentence-transformers/all-MiniLM-L6-v2`
  - Dimensions: 384
  - Format: FLOAT32
  - Speed: ~1ms per embedding
  - Size: 80MB
- **Usage**:
  ```python
  from sentence_transformers import SentenceTransformer
  model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
  embedding = model.encode("text to embed")
  ```
- **Why Chosen**: Best balance of accuracy, speed, and size for semantic search
- **File**: `etl/generate_embeddings.py`

### **PyTorch**
- **Purpose**: Deep learning framework (dependency of sentence-transformers)
- **Usage**: Backend for transformer model inference
- **Note**: CPU-only mode (no GPU required for this dataset size)

### **NumPy**
- **Version**: Latest
- **Purpose**: Numerical computing and array operations
- **Usage**:
  - Array manipulation for embeddings
  - Vector operations
  - Data preprocessing
- **Import**: `import numpy as np`

---

## 🌐 Web Application Layer

### **Streamlit**
- **Version**: 1.50.0
- **Purpose**: Interactive web interface for semantic search
- **Features Used**:
  - Multi-page layouts
  - Sidebar widgets (filters, sliders, multiselect)
  - Session state management
  - Custom CSS styling
  - Expandable result cards
  - Metric displays
- **Usage**: `streamlit run app.py`
- **URL**: http://localhost:8501
- **Why Chosen**: Rapid prototyping, Python-native, great for data apps
- **File**: `app.py`

### **Pandas**
- **Version**: 2.3.3
- **Purpose**: Data manipulation and display
- **Usage**:
  - Convert query results to DataFrames
  - Display tabular data in Streamlit
  - Data aggregation for metrics
- **Import**: `import pandas as pd`

---

## 🛠️ ETL & Data Processing

### **Python Standard Library**

#### **datetime**
- **Purpose**: Date/time handling
- **Usage**:
  - Parse game dates
  - Format timestamps
  - Calculate query times
- **Import**: `from datetime import datetime, timedelta`

#### **json**
- **Purpose**: JSON parsing (minimal use - Oracle handles most JSON)
- **Usage**:
  - Configuration file parsing
  - Debug output formatting
- **Import**: `import json`

#### **sys**
- **Purpose**: System operations
- **Usage**:
  - Path manipulation for imports
  - Exit codes
- **Import**: `import sys`

#### **os**
- **Purpose**: Operating system interactions
- **Usage**:
  - File path operations
  - Environment variable access
- **Import**: `import os`

#### **array**
- **Purpose**: Efficient array storage
- **Usage**:
  - Convert numpy arrays to Python arrays for Oracle
  - Memory-efficient vector storage
- **Import**: `import array`
- **Example**: `vec_array = array.array('f', embedding)`

#### **typing**
- **Purpose**: Type hints for code clarity
- **Usage**:
  - Function signatures
  - Type checking
- **Import**: `from typing import List, Dict, Optional, Any`

#### **warnings**
- **Purpose**: Control warning messages
- **Usage**:
  - Suppress SSL warnings
  - Filter deprecation warnings
- **Import**: `import warnings`

---

## 🗄️ SQL Technologies

### **PL/SQL (Oracle)**
- **Purpose**: Stored procedures for database-native ETL
- **Procedures Created**:
  - **Bronze → Silver**:
    - `sp_load_games` - Extract game metadata
    - `sp_load_goals` - Parse period-by-period scoring
    - `sp_load_players` - Extract player profiles
    - `sp_load_skater_stats` - Parse skater statistics
    - `sp_load_goalie_stats` - Parse goalie statistics
  - **Silver → Gold**:
    - `sp_load_game_narratives` - Prepare games for AI
    - `sp_load_player_season_stats` - Prepare players for AI
- **Why Chosen**: Database-native processing, no data egress, ACID guarantees
- **Files**:
  - `sql/silver_procedures.sql`
  - `sql/gold_procedures.sql`

### **SQL (DDL/DML)**
- **Purpose**: Database schema and data manipulation
- **Files**:
  - `sql/bronze_tables.sql` - Raw data lake tables
  - `sql/silver_tables.sql` - Normalized relational schema
  - `sql/gold_tables.sql` - AI-ready denormalized tables
  - `sql/create_vector_indexes.sql` - HNSW index creation

### **JSON_TABLE() Function (Oracle)**
- **Purpose**: Declarative JSON parsing
- **Usage**: Extract nested JSON into relational columns
- **Example**:
  ```sql
  SELECT jt.*
  FROM bronze_nhl_game_detail b,
       JSON_TABLE(b.api_response, '$.gameData'
         COLUMNS(
           game_id NUMBER PATH '$.game.pk',
           game_date VARCHAR2(20) PATH '$.datetime.dateTime'
         )
       ) jt
  ```
- **Why Chosen**: Native Oracle feature, optimal performance

---

## 🔍 Vector Search Technologies

### **VECTOR Data Type (Oracle 26ai)**
- **Specification**: `VECTOR(384, FLOAT32)`
- **Purpose**: Native storage for embeddings
- **Storage**: ~1.5 KB per vector (384 dimensions × 4 bytes)
- **Benefits**:
  - Optimized memory layout
  - Hardware acceleration
  - Type safety
  - Automatic compression

### **VECTOR_DISTANCE() Function (Oracle 26ai)**
- **Purpose**: Compute similarity between vectors
- **Metrics Supported**:
  - COSINE (used in this project)
  - DOT
  - EUCLIDEAN
  - MANHATTAN
- **Usage**:
  ```sql
  VECTOR_DISTANCE(narrative_vector, :query_vec, COSINE)
  ```
- **Integration**: Works in SELECT, WHERE, ORDER BY clauses

### **HNSW Vector Indexes (Oracle 26ai)**
- **Algorithm**: Hierarchical Navigable Small World
- **Purpose**: Fast approximate nearest neighbor search
- **Configuration**:
  - Distance: COSINE
  - Neighbor Partitions: 4
  - Target Accuracy: 95%
- **Performance**: Sub-10ms queries on 10K vectors
- **Syntax**:
  ```sql
  CREATE VECTOR INDEX idx_game_narratives_vec
  ON gold_game_narratives(narrative_vector)
  ORGANIZATION NEIGHBOR PARTITIONS 4
  DISTANCE COSINE
  WITH TARGET ACCURACY 95;
  ```

---

## 📦 Package Management

### **pip**
- **Version**: 21.2.4 (Python package installer)
- **Purpose**: Install Python dependencies
- **Usage**: `pip3 install --user -r requirements.txt`

### **requirements.txt**
- **Purpose**: Dependency specification
- **Contents**:
  ```
  oracledb>=2.0.0
  sentence-transformers>=2.0.0
  streamlit>=1.30.0
  pandas>=2.0.0
  numpy>=1.24.0
  torch>=2.0.0
  ```

---

## 🖥️ Development Tools

### **VS Code**
- **Purpose**: Integrated development environment
- **Extensions Used** (inferred):
  - Python
  - SQL formatting
  - Markdown preview

### **Git**
- **Purpose**: Version control
- **Repository**: Local project directory
- **Note**: .gitignore recommended for:
  - `__pycache__/`
  - `*.pyc`
  - `.env`
  - `*.log`

### **Docker**
- **Purpose**: Oracle Database containerization
- **Image**: Oracle Database 26ai Free
- **Container Management**: Docker Desktop or Docker CLI

---

## 🌍 External APIs

### **NHL API**
- **Purpose**: Source of raw hockey data
- **Base URL**: NHL Stats API
- **Data Types**:
  - Game details (play-by-play, goals, penalties)
  - Player profiles and statistics
  - Team information
  - Daily scoreboards
- **Format**: JSON
- **Storage**: Bronze layer CLOB columns
- **Note**: API used for data collection (not part of runtime queries)

---

## 📊 Data Formats

### **JSON**
- **Purpose**: API response format and intermediate data
- **Usage**:
  - Bronze layer: Raw API responses
  - Configuration files
- **Processing**: Oracle JSON_TABLE() function

### **CLOB (Character Large Object)**
- **Purpose**: Store large JSON documents
- **Usage**: Bronze layer tables
- **Size**: Up to 4GB per CLOB

### **CSV** (Potential)
- **Purpose**: Data export/import (if needed)
- **Note**: Not currently used but supported via Oracle SQL*Loader

---

## 🎨 Frontend Technologies

### **HTML/CSS**
- **Purpose**: Custom styling in Streamlit
- **Usage**:
  - `st.markdown()` with `unsafe_allow_html=True`
  - Custom CSS classes for result cards, headers
- **File**: `app.py` (embedded in markdown strings)

### **Markdown**
- **Purpose**: Documentation and formatted text
- **Usage**:
  - README files
  - Streamlit text formatting
  - Code documentation
- **Files**:
  - `README.md`
  - `ARCHITECTURE.md`
  - `TEST_RESULTS.md`
  - `WEB_APP_README.md`
  - `TECHNOLOGY_STACK.md` (this file)

---

## 🔧 Configuration & Utilities

### **db_connect.py**
- **Purpose**: Database connection management
- **Features**:
  - Multi-schema connection handler
  - Connection pooling
  - Error handling
  - Configuration via hardcoded credentials (dev mode)
- **Usage**:
  ```python
  from config.db_connect import get_connection
  conn = get_connection('gold')
  ```
- **File**: `config/db_connect.py`

---

## 📁 Project-Specific Modules

### **exploration/hybrid_search.py**
- **Purpose**: Hybrid search engine (semantic + SQL)
- **Class**: `HybridSearchEngine`
- **Methods**:
  - `search_games()` - Search games with filters
  - `search_players()` - Search players with filters
  - `find_similar_players()` - Multi-season similarity
- **Technologies**: oracledb, sentence-transformers, array

### **etl/generate_narratives_enhanced.py**
- **Purpose**: Algorithmic narrative text generation
- **Functions**:
  - `generate_enhanced_game_narrative()` - Game descriptions
  - `generate_enhanced_player_narrative()` - Player descriptions
- **Technologies**: oracledb, datetime

### **etl/generate_embeddings.py**
- **Purpose**: Generate vector embeddings from narratives
- **Technologies**: oracledb, sentence-transformers, numpy, array

### **exploration/validate_improvements.py**
- **Purpose**: Test and validate search precision
- **Technologies**: oracledb, sentence-transformers, array

### **etl/run_complete_etl.py**
- **Purpose**: End-to-end ETL demonstration
- **Technologies**: oracledb, datetime, sys

---

## 🗂️ Architecture Patterns

### **Medallion Architecture**
- **Pattern**: Bronze → Silver → Gold data layers
- **Purpose**: Separate concerns by data maturity
- **Origin**: Databricks best practices
- **Implementation**: 3 Oracle schemas

### **Hybrid Search**
- **Pattern**: Semantic similarity + SQL filters in one query
- **Purpose**: Best of both vector search and traditional databases
- **Unique To**: Oracle 26ai (competitors require separate systems)

### **Vector Embeddings**
- **Pattern**: Text → Dense Vector → Semantic Search
- **Model**: Transformer-based encoder (BERT-derived)
- **Technique**: Sentence embeddings (mean pooling)

---

## 🔐 Security & Access

### **Oracle Database Users**
- **bronze_schema**: Raw data ingestion user
- **silver_schema**: Transformation layer user
- **gold_schema**: Analytics and AI user
- **Note**: Separate users for least privilege principle

### **Authentication**
- **Method**: Username/password (development mode)
- **Storage**: Hardcoded in `config/db_connect.py`
- **Production Recommendation**: Use Oracle Wallet or environment variables

---

## 🚀 Deployment & Runtime

### **Operating System**
- **Platform**: macOS (Darwin 25.2.0)
- **Shell**: zsh
- **Python Path**: `/Applications/Xcode.app/.../python3`

### **Process Management**
- **Streamlit**: Background process via `streamlit run app.py`
- **Database**: Docker container (persistent)
- **Port**: 8501 (Streamlit web interface)

---

## 📈 Performance Tools

### **Timing Measurement**
- **Module**: `datetime` (Python standard library)
- **Usage**: Measure query execution time
- **Example**:
  ```python
  start_time = datetime.now()
  # ... execute query ...
  query_time = (datetime.now() - start_time).total_seconds() * 1000
  ```

### **Query Profiling**
- **Tool**: Oracle EXPLAIN PLAN
- **Purpose**: Analyze query execution plans
- **Usage**: Verify HNSW index usage

---

## 🧪 Testing Technologies

### **Manual Testing**
- **Approach**: Python scripts with visual output
- **Files**:
  - `exploration/validate_improvements.py`
  - `exploration/hybrid_search.py` (demo mode)

### **Validation Metrics**
- **Precision**: Manual evaluation of result relevance
- **Performance**: Query time measurement
- **Coverage**: Count of searchable entities

---

## 📚 Documentation Tools

### **Markdown**
- **Tool**: Native Markdown
- **Viewer**: VS Code / GitHub
- **Files**:
  - 5 major documentation files
  - Inline code comments

### **Docstrings**
- **Format**: Python docstrings (Google style)
- **Purpose**: Function/class documentation
- **Example**:
  ```python
  def search_games(self, query: str, teams: Optional[List[str]] = None):
      """
      Search games combining semantic similarity with filters

      Args:
          query: Natural language search query
          teams: List of team names to filter by

      Returns:
          List of game results with metadata
      """
  ```

---

## 🎯 Technology Selection Rationale

### Why Oracle 26ai?
- ✅ Native VECTOR data type (no BLOB hacks)
- ✅ HNSW indexes for fast ANN search
- ✅ Hybrid queries (semantic + SQL in one query)
- ✅ ACID transactions for vectors
- ✅ No separate vector database needed
- ❌ Requires Oracle 26ai (not available in older versions)

### Why sentence-transformers?
- ✅ State-of-the-art semantic embeddings
- ✅ Lightweight and fast (80MB model)
- ✅ Good accuracy/performance balance
- ✅ Well-documented and maintained
- ❌ Requires Python/PyTorch

### Why Streamlit?
- ✅ Rapid prototyping
- ✅ Python-native (no JavaScript needed)
- ✅ Great for data applications
- ✅ Built-in widgets and layouts
- ❌ Limited customization vs React

### Why PL/SQL for ETL?
- ✅ Database-native processing
- ✅ No data egress
- ✅ ACID guarantees
- ✅ Leverages Oracle optimizer
- ❌ Less portable than Python/dbt

---

## 📊 Technology Summary Table

| Category | Technology | Version | Purpose |
|----------|-----------|---------|---------|
| **Database** | Oracle 26ai Free | 26.0 | Core database + vector search |
| **Language** | Python | 3.9 | ETL, embeddings, application |
| **DB Driver** | oracledb | Latest | Oracle connectivity |
| **ML Framework** | sentence-transformers | Latest | Generate embeddings |
| **ML Backend** | PyTorch | Latest | Transformer inference |
| **Web Framework** | Streamlit | 1.50.0 | Interactive web UI |
| **Data Manipulation** | Pandas | 2.3.3 | Data processing, display |
| **Numerical** | NumPy | Latest | Array operations |
| **Vector Storage** | VECTOR(384, FLOAT32) | Oracle 26ai | Native vector storage |
| **Vector Search** | HNSW Index | Oracle 26ai | Fast ANN search |
| **Similarity** | VECTOR_DISTANCE() | Oracle 26ai | Cosine similarity |
| **ETL** | PL/SQL | Oracle 26ai | Database-native transforms |
| **JSON Parsing** | JSON_TABLE() | Oracle 26ai | JSON → Relational |
| **Upserts** | MERGE | Oracle 26ai | Idempotent ETL |
| **Model** | all-MiniLM-L6-v2 | HuggingFace | 384-dim embeddings |
| **Container** | Docker | Latest | Oracle DB hosting |
| **API** | NHL Stats API | Latest | Data source |

---

## 🔄 Data Flow Through Technologies

```
NHL API (JSON)
    ↓
Oracle CLOB (Bronze Layer)
    ↓
JSON_TABLE() → PL/SQL
    ↓
Relational Tables (Silver Layer)
    ↓
PL/SQL Procedures
    ↓
Denormalized Tables (Gold Layer)
    ↓
Python (generate_narratives_enhanced.py)
    ↓
CLOB narrative_text
    ↓
sentence-transformers (all-MiniLM-L6-v2)
    ↓
NumPy array → Python array
    ↓
Oracle VECTOR(384, FLOAT32)
    ↓
HNSW Index
    ↓
VECTOR_DISTANCE() + SQL Filters
    ↓
oracledb → Python
    ↓
Pandas DataFrame
    ↓
Streamlit Web UI
    ↓
User Browser
```

---

## 📝 Missing Technologies (Not Used)

These technologies are commonly used in similar projects but were **intentionally not used**:

- ❌ **Pinecone/Weaviate/Qdrant** - Separate vector DBs (Oracle 26ai replaces)
- ❌ **Apache Airflow/Prefect** - Workflow orchestration (PL/SQL replaces)
- ❌ **dbt** - Data transformation (PL/SQL replaces)
- ❌ **Spark** - Big data processing (dataset small enough for Oracle)
- ❌ **Redis** - Caching (not needed for current scale)
- ❌ **Elasticsearch** - Full-text search (Oracle handles this)
- ❌ **React/Vue** - Frontend framework (Streamlit replaces)
- ❌ **FastAPI/Flask** - API framework (Streamlit replaces)
- ❌ **OpenAI/Anthropic API** - LLM services (algorithmic generation replaces)
- ❌ **Kubernetes** - Container orchestration (single container sufficient)

**Reason**: Oracle 26ai's native capabilities eliminate the need for most external tools.

---

## 🎓 Learning Resources

- **Oracle 26ai Documentation**: https://docs.oracle.com/en/database/
- **sentence-transformers**: https://www.sbert.net/
- **Streamlit**: https://docs.streamlit.io/
- **HNSW Algorithm**: https://arxiv.org/abs/1603.09320
- **Vector Search**: https://www.pinecone.io/learn/vector-database/

---

*Built for BU 779 Advanced Database Management - Spring 2026*
