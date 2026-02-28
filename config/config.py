"""
Configuration management for NHL Analytics project
Three-schema architecture: bronze → silver → gold
"""
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Application configuration"""

    # ── SportDB API ──────────────────────────────────────────
    SPORTDB_API_KEY  = os.getenv('SPORTDB_API_KEY')
    SPORTDB_BASE_URL = os.getenv('SPORTDB_BASE_URL', 'https://api.sportdb.dev')
    TZ_OFFSET        = int(os.getenv('TZ_OFFSET', 0))

    # ── Oracle - shared settings ─────────────────────────────
    ORACLE_HOST        = os.getenv('ORACLE_HOST', 'localhost')
    ORACLE_SERVICE     = os.getenv('ORACLE_SERVICE', 'FREEPDB1')
    # Ports tried in order when Oracle is in Docker (port can shift on restart)
    ORACLE_PORTS       = [int(p) for p in
                          os.getenv('ORACLE_PORTS', '55000,55001,55002,55003').split(',')]
    ORACLE_TIMEOUT_SEC = int(os.getenv('ORACLE_TIMEOUT_SEC', 10))

    # ── Bronze schema v1 (CLOB, parsed columns) ──────────────
    BRONZE_USER     = os.getenv('BRONZE_USER', 'bronze_schema')
    BRONZE_PASSWORD = os.getenv('BRONZE_PASSWORD')

    # ── Bronze schema v2 (1 table/endpoint, native JSON OSON) ─
    BRONZE_2_USER     = os.getenv('BRONZE_2_USER', 'bronze_2')
    BRONZE_2_PASSWORD = os.getenv('BRONZE_2_PASSWORD')

    # ── Silver schema (structured OLTP) ─────────────────────
    SILVER_USER     = os.getenv('SILVER_USER', 'silver_schema')
    SILVER_PASSWORD = os.getenv('SILVER_PASSWORD')

    # ── Gold schema (refined data + vector search) ───────────
    GOLD_USER     = os.getenv('GOLD_USER', 'gold_schema')
    GOLD_PASSWORD = os.getenv('GOLD_PASSWORD')

    # ── Local directories ─────────────────────────────────────
    DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
    SQL_DIR  = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'sql')

    @classmethod
    def validate_api(cls):
        """Validate SportDB API config only."""
        if not cls.SPORTDB_API_KEY:
            raise ValueError("SPORTDB_API_KEY not set in .env")

    @classmethod
    def validate(cls):
        """Validate API + at least bronze DB config."""
        errors = []
        if not cls.SPORTDB_API_KEY:
            errors.append("SPORTDB_API_KEY not set in .env")
        if not cls.BRONZE_PASSWORD:
            errors.append("BRONZE_PASSWORD not set in .env")
        if errors:
            raise ValueError("Configuration errors:\n" + "\n".join(errors))

    @classmethod
    def schema_credentials(cls, schema: str) -> tuple:
        """Return (user, password) for the requested schema tier."""
        mapping = {
            'bronze':   (cls.BRONZE_USER,   cls.BRONZE_PASSWORD),
            'bronze_2': (cls.BRONZE_2_USER, cls.BRONZE_2_PASSWORD),
            'silver':   (cls.SILVER_USER,   cls.SILVER_PASSWORD),
            'gold':     (cls.GOLD_USER,     cls.GOLD_PASSWORD),
        }
        if schema not in mapping:
            raise ValueError(f"Unknown schema tier '{schema}'. Use: bronze, bronze_2, silver, gold")
        return mapping[schema]


os.makedirs(Config.DATA_DIR, exist_ok=True)
