"""
NHL Official API Loader v3 - Bronze Layer  (Two-Phase: Extract → Load)
=======================================================================
Source: api-web.nhle.com  (no API key required)

Introduces a local file cache between the API and Oracle:

  Phase 1 – EXTRACT:  API  →  local JSON files   (data/cache/nhl/)
  Phase 2 – LOAD:     local JSON files  →  Oracle Bronze (bronze_2)

Why?
  • Eliminates the API as a single point of failure during DB loads
  • Allows retrying the DB load without re-hitting the NHL API
  • Makes the per-phase cost visible (API latency vs DB insert latency)
  • Lets you compare v3 (two-phase) total time vs v2 (inline) total time

Cache layout:
  {cache_dir}/score/{date}.json
  {cache_dir}/landing/{game_id}.json
  {cache_dir}/boxscore/{game_id}.json

Usage:
  # Full pipeline (extract then load)
  python etl/load_nhl_v3.py --date 2026-02-17
  python etl/load_nhl_v3.py --season 20252026
  python etl/load_nhl_v3.py --backfill-seasons

  # Phase 1 only — fetch from API and write files, no DB
  python etl/load_nhl_v3.py --date 2026-02-17 --extract-only

  # Phase 2 only — load from existing cache into Oracle, no API calls
  python etl/load_nhl_v3.py --date 2026-02-17 --load-only

  # Custom cache directory
  python etl/load_nhl_v3.py --date 2026-02-17 --cache-dir /tmp/nhl_cache
"""

import sys, os, json, time, argparse
from datetime import date, datetime
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import oracledb
from config.db_connect import get_connection

BASE    = "https://api-web.nhle.com"
LOG_PFX = "[NHLv3]"
DELAY   = 0.2   # polite delay between per-game API calls (seconds)

AVAILABLE_SEASONS = [
    20202021, 20212022, 20222023,
    20232024, 20242025, 20252026,
]

DEFAULT_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "cache", "nhl"
)


# ── Timing accumulator ────────────────────────────────────────

@dataclass
class Timings:
    """Accumulates per-phase timing and count data."""
    api_s:          float = 0.0   # Phase 1: seconds spent on API fetches
    write_s:        float = 0.0   # Phase 1: seconds spent writing JSON to disk
    read_s:         float = 0.0   # Phase 2: seconds spent reading JSON from disk
    db_s:           float = 0.0   # Phase 2: seconds spent on Oracle inserts

    games_fetched:  int = 0       # API calls made (score endpoints)
    details_fetched: int = 0      # API calls made (landing + boxscore pairs)
    files_written:  int = 0       # JSON files written to disk
    files_skipped:  int = 0       # files already on disk (cache hits)
    rows_inserted:  int = 0       # Oracle rows inserted
    rows_skipped:   int = 0       # Oracle rows already present (idempotent)
    errors:         int = 0

    def add(self, other: "Timings"):
        for f in self.__dataclass_fields__:
            setattr(self, f, getattr(self, f) + getattr(other, f))

    # Convenience averages
    @property
    def avg_api_ms(self) -> float:
        n = self.details_fetched or 1
        return self.api_s / n * 1000

    @property
    def avg_write_ms(self) -> float:
        n = self.files_written or 1
        return self.write_s / n * 1000

    @property
    def avg_read_ms(self) -> float:
        n = self.rows_inserted or 1
        return self.read_s / n * 1000

    @property
    def avg_db_ms(self) -> float:
        n = self.rows_inserted or 1
        return self.db_s / n * 1000


# ── Cache helpers ─────────────────────────────────────────────

def cache_path(cache_dir: str, kind: str, key: str) -> Path:
    """Return Path for a cached file. kind in {score, landing, boxscore}."""
    p = Path(cache_dir) / kind
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{key}.json"


def write_json(path: Path, data: dict) -> float:
    """Write data to path as JSON. Returns elapsed seconds."""
    t0 = time.perf_counter()
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return time.perf_counter() - t0


def read_json(path: Path) -> tuple[dict, float]:
    """Read JSON from path. Returns (data, elapsed_seconds)."""
    t0 = time.perf_counter()
    data = json.loads(path.read_text(encoding="utf-8"))
    elapsed = time.perf_counter() - t0
    return data, elapsed


def cache_size_mb(cache_dir: str) -> float:
    """Return total size of cache directory in MB."""
    total = sum(f.stat().st_size for f in Path(cache_dir).rglob("*.json") if f.is_file())
    return total / 1024 / 1024


# ── API helpers ───────────────────────────────────────────────

_RETRY_DELAYS = [5, 15, 30]   # seconds between retries (3 attempts)

def _api_get(url: str) -> tuple[dict, float]:
    """GET a URL and return (json_dict, elapsed_seconds).
    Retries up to 3 times on transient connection errors with backoff."""
    t0 = time.perf_counter()
    last_err = None
    for attempt, delay in enumerate([0] + _RETRY_DELAYS):
        if delay:
            print(f"{LOG_PFX}   retrying in {delay}s (attempt {attempt+1}/3)...")
            time.sleep(delay)
        try:
            r = requests.get(url, headers={"User-Agent": "NHL-Analytics-BU779/1.0"}, timeout=20)
            r.raise_for_status()
            return r.json(), time.perf_counter() - t0
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            last_err = e
            continue
    raise last_err


def fetch_score(game_date: str) -> tuple[dict, float]:
    return _api_get(f"{BASE}/v1/score/{game_date}")


def fetch_landing(game_id: int) -> tuple[dict, float]:
    return _api_get(f"{BASE}/v1/gamecenter/{game_id}/landing")


def fetch_boxscore(game_id: int) -> tuple[dict, float]:
    return _api_get(f"{BASE}/v1/gamecenter/{game_id}/boxscore")


def fetch_season_dates(season: int) -> list[str]:
    data, _ = _api_get(f"{BASE}/v1/club-schedule-season/BUF/{season}")
    return sorted({
        g["gameDate"]
        for g in data.get("games", [])
        if g.get("gameType") == 2 and g.get("gameState") in ("OFF", "FINAL", "F")
    })


def _to_date(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()


# ── Oracle helpers ────────────────────────────────────────────

def score_loaded(cur, game_date) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM bronze_nhl_score WHERE game_date = :1",
        (game_date,)
    )
    return cur.fetchone()[0] > 0


def landing_loaded(cur, game_id: int) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM bronze_nhl_landing WHERE game_id = :1",
        (game_id,)
    )
    return cur.fetchone()[0] > 0


def boxscore_loaded(cur, game_id: int) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM bronze_nhl_boxscore WHERE game_id = :1",
        (game_id,)
    )
    return cur.fetchone()[0] > 0


def insert_score(cur, conn, game_date, data: dict) -> float:
    cur.setinputsizes(None, oracledb.DB_TYPE_JSON)
    t0 = time.perf_counter()
    cur.execute(
        "INSERT INTO bronze_nhl_score (game_date, raw_response) VALUES (:1, :2)",
        (game_date, data)
    )
    conn.commit()
    return time.perf_counter() - t0


def insert_landing(cur, conn, game_id: int, game_date, data: dict) -> float:
    cur.setinputsizes(None, None, oracledb.DB_TYPE_JSON)
    t0 = time.perf_counter()
    cur.execute(
        "INSERT INTO bronze_nhl_landing (game_id, game_date, raw_response) VALUES (:1, :2, :3)",
        (game_id, game_date, data)
    )
    conn.commit()
    return time.perf_counter() - t0


def insert_boxscore(cur, conn, game_id: int, game_date, data: dict) -> float:
    cur.setinputsizes(None, None, oracledb.DB_TYPE_JSON)
    t0 = time.perf_counter()
    cur.execute(
        "INSERT INTO bronze_nhl_boxscore (game_id, game_date, raw_response) VALUES (:1, :2, :3)",
        (game_id, game_date, data)
    )
    conn.commit()
    return time.perf_counter() - t0


def log_result(cur, conn, source, game_date, fetched, inserted, status, msg=None):
    d = _to_date(game_date) if isinstance(game_date, str) else game_date
    try:
        cur.callproc("bronze_log", [source, d, fetched, inserted, status, msg or ""])
        conn.commit()
    except Exception:
        pass  # logging failure should not abort the pipeline


# ── bronze_schema helpers (CLOB, merged landing+boxscore per game) ────────────

def detail_loaded_bronze(cur, game_id: int) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM bronze_nhl_game_detail WHERE game_id = :1",
        (game_id,)
    )
    return cur.fetchone()[0] > 0


def daily_loaded_bronze(cur, game_date) -> bool:
    cur.execute(
        "SELECT COUNT(*) FROM bronze_nhl_daily WHERE game_date = :1",
        (game_date,)
    )
    return cur.fetchone()[0] > 0


def insert_daily_bronze(cur, conn, game_date, game_count: int, data: dict) -> float:
    """Insert daily score summary into bronze_schema (CLOB column — needs json.dumps)."""
    t0 = time.perf_counter()
    cur.execute(
        "INSERT INTO bronze_nhl_daily (game_date, game_count, raw_response) VALUES (:1, :2, :3)",
        (game_date, game_count, json.dumps(data))   # CLOB requires a string, not dict
    )
    conn.commit()
    return time.perf_counter() - t0


def insert_game_detail_bronze(cur, conn, game_id: int,
                               landing: dict, boxscore: dict) -> float:
    """Insert merged landing+boxscore into bronze_schema (CLOB columns, v1 pattern)."""
    g_date_str = landing.get("gameDate", "")
    g_date     = _to_date(g_date_str) if g_date_str else None
    season     = landing.get("season")
    game_type  = landing.get("gameType")
    home       = landing.get("homeTeam", {}).get("abbrev", "")
    away       = landing.get("awayTeam", {}).get("abbrev", "")
    h_score    = landing.get("homeTeam", {}).get("score")
    a_score    = landing.get("awayTeam", {}).get("score")
    state      = landing.get("gameState", "")

    t0 = time.perf_counter()
    cur.execute(
        """INSERT INTO bronze_nhl_game_detail
            (game_id, game_date, season, game_type,
             home_team, away_team, home_score, away_score, game_state,
             landing_json, boxscore_json)
           VALUES (:1, :2, :3, :4, :5, :6, :7, :8, :9, :10, :11)""",
        (game_id, g_date, season, game_type,
         home, away, h_score, a_score, state,
         json.dumps(landing), json.dumps(boxscore))   # CLOB requires strings
    )
    conn.commit()
    return time.perf_counter() - t0


# ── Phase 1: EXTRACT  (API → local files) ────────────────────

def extract_date(game_date_str: str, cache_dir: str, timings: Timings):
    """
    Fetch score summary + per-game landing/boxscore from the NHL API
    and write each payload to a local JSON file.  Skips files that
    already exist on disk.
    """
    d = _to_date(game_date_str)

    # ── Score summary ────────────────────────────────────────
    score_file = cache_path(cache_dir, "score", game_date_str)
    if score_file.exists():
        timings.files_skipped += 1
        # Still need to read it to discover game IDs
        score_data, _ = read_json(score_file)
        print(f"{LOG_PFX} {game_date_str}: score already cached, skipping API call")
    else:
        try:
            score_data, api_t = fetch_score(game_date_str)
            timings.api_s     += api_t
            timings.games_fetched += 1

            write_t = write_json(score_file, score_data)
            timings.write_s     += write_t
            timings.files_written += 1
            print(f"{LOG_PFX} {game_date_str}: score fetched ({api_t*1000:.0f}ms api, "
                  f"{write_t*1000:.1f}ms write)")
        except Exception as e:
            timings.errors += 1
            print(f"{LOG_PFX} {game_date_str}: EXTRACT ERROR (score) - {e}")
            return   # skip per-game details for this date

    # ── Per-game details ──────────────────────────────────────
    games = [
        g for g in score_data.get("games", [])
        if g.get("gameType") == 2 and g.get("gameState") in ("OFF", "FINAL", "F")
    ]

    detail_count = 0
    for g in games:
        gid = g["id"]

        landing_file  = cache_path(cache_dir, "landing",  str(gid))
        boxscore_file = cache_path(cache_dir, "boxscore", str(gid))

        landing_cached  = landing_file.exists()
        boxscore_cached = boxscore_file.exists()

        if landing_cached and boxscore_cached:
            timings.files_skipped += 2
            continue

        time.sleep(DELAY)

        try:
            if not landing_cached:
                data, api_t      = fetch_landing(gid)
                timings.api_s   += api_t
                write_t          = write_json(landing_file, data)
                timings.write_s += write_t
                timings.files_written += 1

            if not boxscore_cached:
                data, api_t      = fetch_boxscore(gid)
                timings.api_s   += api_t
                write_t          = write_json(boxscore_file, data)
                timings.write_s += write_t
                timings.files_written += 1

            timings.details_fetched += 1
            detail_count += 1

        except Exception as e:
            timings.errors += 1
            print(f"{LOG_PFX}   game {gid}: EXTRACT ERROR - {e}")

    if detail_count:
        print(f"{LOG_PFX} {game_date_str}: {detail_count} game details cached")


# ── Phase 2: LOAD  (local files → Oracle) ────────────────────

def load_date_from_cache(game_date_str: str, cache_dir: str,
                         conn, timings: Timings):
    """
    Read cached JSON files for game_date_str and insert into Oracle
    bronze_2 tables.  Skips rows that are already present (idempotent).
    """
    d   = _to_date(game_date_str)
    cur = conn.cursor()

    try:
        # ── Score ────────────────────────────────────────────
        score_file = cache_path(cache_dir, "score", game_date_str)
        if not score_file.exists():
            print(f"{LOG_PFX} {game_date_str}: no score file in cache, skipping")
            cur.close()
            return

        score_data, read_t = read_json(score_file)
        timings.read_s    += read_t

        games = [
            g for g in score_data.get("games", [])
            if g.get("gameType") == 2 and g.get("gameState") in ("OFF", "FINAL", "F")
        ]
        if not games:
            cur.close()
            return

        if score_loaded(cur, d):
            timings.rows_skipped += 1
        else:
            db_t               = insert_score(cur, conn, d, score_data)
            timings.db_s      += db_t
            timings.rows_inserted += 1
            log_result(cur, conn, "NHL_SCORE_V3", d, len(games), 1, "SUCCESS")

        # ── Per-game details ──────────────────────────────────
        detail_count = 0
        for g in games:
            gid = g["id"]

            landing_file  = cache_path(cache_dir, "landing",  str(gid))
            boxscore_file = cache_path(cache_dir, "boxscore", str(gid))

            try:
                # Landing
                if not landing_file.exists():
                    print(f"{LOG_PFX}   game {gid}: no landing file in cache, skipping")
                elif landing_loaded(cur, gid):
                    timings.rows_skipped += 1
                else:
                    data, read_t       = read_json(landing_file)
                    timings.read_s    += read_t
                    gdate              = _to_date(data.get("gameDate", game_date_str))
                    db_t               = insert_landing(cur, conn, gid, gdate, data)
                    timings.db_s      += db_t
                    timings.rows_inserted += 1

                # Boxscore
                if not boxscore_file.exists():
                    print(f"{LOG_PFX}   game {gid}: no boxscore file in cache, skipping")
                elif boxscore_loaded(cur, gid):
                    timings.rows_skipped += 1
                else:
                    data, read_t       = read_json(boxscore_file)
                    timings.read_s    += read_t
                    db_t               = insert_boxscore(cur, conn, gid, d, data)
                    timings.db_s      += db_t
                    timings.rows_inserted += 1

                detail_count += 1

            except Exception as e:
                timings.errors += 1
                print(f"{LOG_PFX}   game {gid}: LOAD ERROR - {e}")
                try:
                    log_result(cur, conn, "NHL_LANDING_V3", d, 0, 0, "ERROR", str(e)[:4000])
                except Exception:
                    pass

        if detail_count:
            print(f"{LOG_PFX} {game_date_str}: {detail_count} game details loaded from cache")

    except Exception as e:
        timings.errors += 1
        print(f"{LOG_PFX} {game_date_str}: LOAD ERROR - {e}")
    finally:
        cur.close()


# ── Phase 2: LOAD into bronze_schema (CLOB, merged rows) ─────

def load_date_from_cache_bronze(game_date_str: str, cache_dir: str,
                                 conn, timings: Timings):
    """
    Read cached JSON files and insert into bronze_schema (production CLOB tables).
    Landing + boxscore are merged into a single row per game, matching v1's schema.
    """
    d   = _to_date(game_date_str)
    cur = conn.cursor()

    try:
        score_file = cache_path(cache_dir, "score", game_date_str)
        if not score_file.exists():
            print(f"{LOG_PFX} {game_date_str}: no score file in cache, skipping")
            cur.close()
            return

        score_data, read_t = read_json(score_file)
        timings.read_s    += read_t

        games = [
            g for g in score_data.get("games", [])
            if g.get("gameType") == 2 and g.get("gameState") in ("OFF", "FINAL", "F")
        ]
        if not games:
            cur.close()
            return

        # Daily summary row
        if daily_loaded_bronze(cur, d):
            timings.rows_skipped += 1
        else:
            db_t               = insert_daily_bronze(cur, conn, d, len(games), score_data)
            timings.db_s      += db_t
            timings.rows_inserted += 1
            log_result(cur, conn, "NHL_DAILY_V3B", d, len(games), 1, "SUCCESS")

        # Per-game detail rows (landing + boxscore merged)
        detail_count = 0
        for g in games:
            gid           = g["id"]
            landing_file  = cache_path(cache_dir, "landing",  str(gid))
            boxscore_file = cache_path(cache_dir, "boxscore", str(gid))

            try:
                if detail_loaded_bronze(cur, gid):
                    timings.rows_skipped += 1
                    continue

                if not landing_file.exists() or not boxscore_file.exists():
                    print(f"{LOG_PFX}   game {gid}: missing cache file, skipping")
                    continue

                landing,  read_t = read_json(landing_file)
                timings.read_s  += read_t
                boxscore, read_t = read_json(boxscore_file)
                timings.read_s  += read_t

                db_t               = insert_game_detail_bronze(cur, conn, gid, landing, boxscore)
                timings.db_s      += db_t
                timings.rows_inserted += 1
                detail_count      += 1

            except Exception as e:
                timings.errors += 1
                print(f"{LOG_PFX}   game {gid}: LOAD ERROR - {e}")
                try:
                    log_result(cur, conn, "NHL_DETAIL_V3B", d, 0, 0, "ERROR", str(e)[:4000])
                except Exception:
                    pass

        if detail_count:
            print(f"{LOG_PFX} {game_date_str}: {detail_count} game details loaded from cache")

    except Exception as e:
        timings.errors += 1
        print(f"{LOG_PFX} {game_date_str}: LOAD ERROR - {e}")
    finally:
        cur.close()


# ── Season-level orchestration ────────────────────────────────

def extract_season(season: int, cache_dir: str, timings: Timings):
    print(f"{LOG_PFX} Phase 1 – extracting season {season}...")
    try:
        dates = fetch_season_dates(season)
        print(f"{LOG_PFX}   {len(dates)} game dates")
    except Exception as e:
        timings.errors += 1
        print(f"{LOG_PFX} Season {season}: ERROR fetching schedule - {e}")
        return
    for d in dates:
        extract_date(d, cache_dir, timings)


def load_season_from_cache(season: int, cache_dir: str, conn,
                           timings: Timings, target: str = "bronze_2"):
    print(f"{LOG_PFX} Phase 2 – loading season {season} from cache → {target}...")
    score_dir = Path(cache_dir) / "score"
    if not score_dir.exists():
        print(f"{LOG_PFX}   No cache found at {score_dir}")
        return
    season_str = str(season)
    score_files = sorted(score_dir.glob("*.json"))
    season_dates = []
    for sf in score_files:
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            games = data.get("games", [])
            if any(str(g.get("season", "")) == season_str for g in games):
                season_dates.append(sf.stem)
        except Exception:
            continue
    print(f"{LOG_PFX}   {len(season_dates)} cached dates for season {season}")
    loader = (load_date_from_cache_bronze if target == "bronze"
              else load_date_from_cache)
    for d in season_dates:
        loader(d, cache_dir, conn, timings)


# ── Benchmark summary printer ─────────────────────────────────

def print_benchmark(p1: Timings, p2: Timings, cache_dir: str, mode: str,
                    target: str = "bronze_2"):
    sep  = "─" * 65
    sep2 = "═" * 65

    schema_label = "bronze_schema (CLOB)" if target == "bronze" else "bronze_2 (OSON)"
    print(f"\n{sep2}")
    print(f"  ETL BENCHMARK SUMMARY  [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    print(f"  Target schema: {schema_label}")
    print(f"{sep2}")

    if mode != "load-only":
        print(f"\n  PHASE 1 — EXTRACT  (API → Local Files)")
        print(f"  {sep}")
        print(f"  {'Score dates fetched:':<35} {p1.games_fetched:>8,}")
        print(f"  {'Game details fetched (land+box):':<35} {p1.details_fetched:>8,}")
        print(f"  {'Files written to disk:':<35} {p1.files_written:>8,}")
        print(f"  {'Files already cached (skipped):':<35} {p1.files_skipped:>8,}")
        print(f"  {'Errors:':<35} {p1.errors:>8,}")
        print()
        print(f"  {'API fetch time:':<35} {p1.api_s:>8.1f}s  (avg {p1.avg_api_ms:.0f} ms/game)")
        print(f"  {'File write time:':<35} {p1.write_s:>8.2f}s  (avg {p1.avg_write_ms:.1f} ms/file)")
        print(f"  {'Phase 1 total:':<35} {p1.api_s + p1.write_s:>8.1f}s")

        try:
            sz = cache_size_mb(cache_dir)
            print(f"\n  Cache size on disk:  {sz:.1f} MB  ({cache_dir})")
        except Exception:
            pass

    if mode != "extract-only":
        print(f"\n  PHASE 2 — LOAD  (Local Files → Oracle)")
        print(f"  {sep}")
        print(f"  {'Oracle rows inserted:':<35} {p2.rows_inserted:>8,}")
        print(f"  {'Oracle rows already present:':<35} {p2.rows_skipped:>8,}")
        print(f"  {'Errors:':<35} {p2.errors:>8,}")
        print()
        print(f"  {'File read time:':<35} {p2.read_s:>8.2f}s  (avg {p2.avg_read_ms:.1f} ms/row)")
        print(f"  {'DB insert time:':<35} {p2.db_s:>8.2f}s  (avg {p2.avg_db_ms:.1f} ms/row)")
        print(f"  {'Phase 2 total:':<35} {p2.read_s + p2.db_s:>8.1f}s")

    if mode == "both":
        p1_total   = p1.api_s + p1.write_s
        p2_total   = p2.read_s + p2.db_s
        v3_total   = p1_total + p2_total
        inline_est = p1.api_s + p2.db_s   # inline = same API + same DB, no file I/O
        overhead   = v3_total - inline_est
        pct        = (overhead / inline_est * 100) if inline_est > 0 else 0

        inline_label = "v1 inline" if target == "bronze" else "v2 inline"
        print(f"\n  {sep}")
        print(f"  COMPARISON vs {inline_label} (API → Oracle, no staging)")
        print(f"  {sep}")
        print(f"  {'v3 total (Phase 1 + Phase 2):':<35} {v3_total:>8.1f}s")
        print(f"  {f'{inline_label} estimated (API + DB):':<35} {inline_est:>8.1f}s")
        print(f"  {'File I/O overhead:':<35} {overhead:>+8.1f}s  ({pct:+.1f}%)")
        print()
        print(f"  File write: {p1.write_s:.2f}s   File read: {p2.read_s:.2f}s")
        print(f"  Combined file I/O: {p1.write_s + p2.read_s:.2f}s vs "
              f"API time {p1.api_s:.1f}s — "
              f"file I/O is {(p1.write_s + p2.read_s)/p1.api_s*100:.1f}% of API time")
        print()
        print(f"  BENEFIT: crash recovery without API re-hits")
        print(f"           (Phase 2 alone: {p2_total:.1f}s, no API needed)")

    print(f"\n{sep2}\n")


# ── Main ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="NHL Bronze v3 Loader — two-phase Extract→Load with benchmarking"
    )

    # Scope
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--date",             help="Single date YYYY-MM-DD")
    scope.add_argument("--season",           type=int, help="Season e.g. 20252026")
    scope.add_argument("--backfill-seasons", action="store_true",
                       help="All 6 available seasons")

    # Phase control
    phase = parser.add_mutually_exclusive_group()
    phase.add_argument("--extract-only", action="store_true",
                       help="Phase 1 only: API → local files, skip Oracle load")
    phase.add_argument("--load-only",    action="store_true",
                       help="Phase 2 only: local files → Oracle, skip API fetch")

    parser.add_argument("--cache-dir", default=DEFAULT_CACHE_DIR,
                        help=f"Local file cache root (default: {DEFAULT_CACHE_DIR})")
    parser.add_argument("--target", choices=["bronze", "bronze_2"], default="bronze_2",
                        help=("Oracle schema for Phase 2 load: "
                              "'bronze' = bronze_schema (CLOB, production pipeline) | "
                              "'bronze_2' = bronze_2 (OSON, default)"))
    args = parser.parse_args()

    if args.extract_only:
        mode = "extract-only"
    elif args.load_only:
        mode = "load-only"
    else:
        mode = "both"

    schema_label = "bronze_schema (CLOB)" if args.target == "bronze" else "bronze_2 (OSON)"
    print("=" * 65)
    print("NHL BRONZE v3 LOADER  (Two-Phase: Extract → Load)")
    print(f"Started : {datetime.now().isoformat()}")
    print(f"Mode    : {mode}")
    print(f"Target  : {schema_label}")
    print(f"Cache   : {args.cache_dir}")
    print("=" * 65)

    p1 = Timings()
    p2 = Timings()

    # ── Phase 1: Extract ──────────────────────────────────────
    if mode != "load-only":
        t_phase1_start = time.perf_counter()
        print(f"\n{'─'*65}")
        print(f"  PHASE 1 — EXTRACT  (API → Local Files)")
        print(f"{'─'*65}")

        if args.date:
            extract_date(args.date, args.cache_dir, p1)
        elif args.season:
            extract_season(args.season, args.cache_dir, p1)
        elif args.backfill_seasons:
            for season in AVAILABLE_SEASONS:
                extract_season(season, args.cache_dir, p1)
        else:
            # Default: today
            extract_date(str(date.today()), args.cache_dir, p1)

        p1_elapsed = time.perf_counter() - t_phase1_start
        print(f"\n  Phase 1 done in {p1_elapsed:.1f}s  "
              f"({p1.files_written} files written, {p1.files_skipped} cached)")

    # ── Phase 2: Load ─────────────────────────────────────────
    if mode != "extract-only":
        t_phase2_start = time.perf_counter()
        print(f"\n{'─'*65}")
        print(f"  PHASE 2 — LOAD  (Local Files → Oracle)")
        print(f"{'─'*65}")

        conn = get_connection(args.target)

        if args.target == "bronze":
            load_date_fn = load_date_from_cache_bronze
            def load_season_fn(s, c, cn, t):
                load_season_from_cache(s, c, cn, t, target="bronze")
        else:
            load_date_fn = load_date_from_cache
            def load_season_fn(s, c, cn, t):
                load_season_from_cache(s, c, cn, t, target="bronze_2")

        if args.date:
            load_date_fn(args.date, args.cache_dir, conn, p2)
        elif args.season:
            load_season_fn(args.season, args.cache_dir, conn, p2)
        elif args.backfill_seasons:
            for season in AVAILABLE_SEASONS:
                load_season_fn(season, args.cache_dir, conn, p2)
        else:
            load_date_fn(str(date.today()), args.cache_dir, conn, p2)

        conn.close()
        p2_elapsed = time.perf_counter() - t_phase2_start
        print(f"\n  Phase 2 done in {p2_elapsed:.1f}s  "
              f"({p2.rows_inserted} rows inserted, {p2.rows_skipped} skipped)")

    # ── Benchmark summary ─────────────────────────────────────
    print_benchmark(p1, p2, args.cache_dir, mode, target=args.target)

    print(f"Finished: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
