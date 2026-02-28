"""
Oracle connection utility with Docker-aware port discovery.

Oracle running in Docker may bind to a different host port on each container
restart (55000, 55001, 55002, or 55003). This module tries each port in order
and returns the first successful connection.

Total wall-clock budget is ORACLE_TIMEOUT_SEC (default 10 s). If no port
responds within that budget the call raises OracleConnectionError.

Usage:
    from config.db_connect import get_connection

    conn = get_connection('bronze')   # bronze_schema user
    conn = get_connection('silver')   # silver_schema user
    conn = get_connection('gold')     # gold_schema user
    conn = get_connection('system', user='SYSTEM', password='Apollo55!')
"""

import time
import socket
import sys
import os

# Resolve project root and load Config regardless of how this file is invoked
_THIS_DIR     = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)

# When run as a script, Python adds config/ to sys.path which shadows the
# config package from the project root. Remove it, then add the project root.
if _THIS_DIR in sys.path:
    sys.path.remove(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from config.config import Config

try:
    import oracledb
except ImportError:
    raise ImportError(
        "oracledb not installed. Run: pip install oracledb"
    )


class OracleConnectionError(Exception):
    """Raised when no Oracle port is reachable within the timeout."""


def _port_open(host: str, port: int, timeout: float) -> bool:
    """Return True if a TCP connection to host:port succeeds within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def find_oracle_port(
    host: str = None,
    ports: list = None,
    total_timeout: float = None
) -> int:
    """
    Probe ports in order and return the first one that accepts a TCP connection.
    Raises OracleConnectionError if none respond within total_timeout seconds.
    """
    host          = host          or Config.ORACLE_HOST
    ports         = ports         or Config.ORACLE_PORTS
    total_timeout = total_timeout or Config.ORACLE_TIMEOUT_SEC

    deadline    = time.monotonic() + total_timeout
    per_port    = max(0.5, total_timeout / len(ports))

    for port in ports:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        probe = min(per_port, remaining)
        if _port_open(host, port, probe):
            return port

    raise OracleConnectionError(
        f"Oracle not reachable on {host} ports {ports} "
        f"within {total_timeout}s. Is the Docker container running?"
    )


def get_connection(
    schema: str = 'bronze',
    user: str = None,
    password: str = None,
    host: str = None,
    ports: list = None,
    service: str = None,
    total_timeout: float = None,
    verbose: bool = True
):
    """
    Return an oracledb connection for the requested schema tier.

    Parameters
    ----------
    schema   : 'bronze' | 'silver' | 'gold'  (ignored if user/password given)
    user     : override schema user
    password : override schema password
    host     : override ORACLE_HOST
    ports    : override ORACLE_PORTS list
    service  : override ORACLE_SERVICE
    total_timeout : seconds before giving up (default ORACLE_TIMEOUT_SEC)
    verbose  : print which port was found

    Returns
    -------
    oracledb.Connection
    """
    host    = host    or Config.ORACLE_HOST
    ports   = ports   or Config.ORACLE_PORTS
    service = service or Config.ORACLE_SERVICE
    total_timeout = total_timeout or Config.ORACLE_TIMEOUT_SEC

    # Resolve credentials
    if user is None or password is None:
        user, password = Config.schema_credentials(schema)

    # Discover active port
    port = find_oracle_port(host, ports, total_timeout)

    if verbose:
        print(f"[db_connect] Oracle found on {host}:{port}/{service} → connecting as {user}")

    dsn  = f"{host}:{port}/{service}"
    conn = oracledb.connect(user=user, password=password, dsn=dsn)
    return conn


# ── Quick self-test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json

    print("Testing Oracle port discovery...")
    try:
        # Test with SYSTEM first so we can list schemas without needing them created
        conn = get_connection(
            schema='bronze',
            user='SYSTEM',
            password=os.getenv('SYSTEM_PASSWORD', 'Apollo55!')
        )
        cur = conn.cursor()
        cur.execute("SELECT banner FROM v$version WHERE ROWNUM = 1")
        print(f"Connected: {cur.fetchone()[0]}")

        cur.execute(
            "SELECT username FROM dba_users "
            "WHERE username IN ('BRONZE_SCHEMA','SILVER_SCHEMA','GOLD_SCHEMA') "
            "ORDER BY username"
        )
        existing = [r[0] for r in cur.fetchall()]
        print(f"Schema users found: {existing or 'none yet'}")

        cur.close()
        conn.close()
        print("Self-test passed.")

    except OracleConnectionError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
