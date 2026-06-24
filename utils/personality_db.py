"""Database backend shim for PersonalityManager.

Returns ``(conn, placeholder, backend)`` where ``placeholder`` is '?' for SQLite
or '%s' for Postgres and ``backend`` is the string 'sqlite' or 'postgres' (used
to pick the right DDL via :func:`ddl_soul_versions` / :func:`ddl_interactions`).
Switch to Postgres by setting CYCLAW_DB_URL or personality.database_url in
config.yaml to a postgresql:// DSN. Default is SQLite (zero-config, local-first).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def connect(db_path: Path, pers_cfg: dict) -> tuple[Any, str, str]:
    """Open a DB connection and return ``(conn, placeholder_char, backend_name)``.

    Postgres: set CYCLAW_DB_URL=postgresql://user:pass@host/dbname
    SQLite:   default, uses db_path resolved from config.

    ``conn`` is a ``sqlite3.Connection`` or a ``psycopg.Connection`` (typed
    ``Any`` so importing psycopg stays optional for SQLite-only installs).
    """
    dsn = os.environ.get("CYCLAW_DB_URL") or pers_cfg.get("database_url") or ""
    if dsn.startswith("postgresql") or dsn.startswith("postgres"):
        try:
            import psycopg  # type: ignore[import]
            from psycopg.rows import dict_row  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "psycopg is required for PostgreSQL support. "
                "Install it with: pip install 'psycopg[binary]'"
            ) from exc
        conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=False)
        return conn, "%s", "postgres"
    # Default: SQLite (offline-first, zero-config)
    import sqlite3
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn, "?", "sqlite"


def ddl_soul_versions(backend: str) -> str:
    if backend == "postgres":
        return """
            CREATE TABLE IF NOT EXISTS soul_versions (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                sha256 TEXT NOT NULL,
                content TEXT NOT NULL,
                reason TEXT,
                timestamp TEXT NOT NULL
            )
        """
    return """
        CREATE TABLE IF NOT EXISTS soul_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sha256 TEXT NOT NULL,
            content TEXT NOT NULL,
            reason TEXT,
            timestamp TEXT NOT NULL
        )
    """


def ddl_interactions(backend: str) -> str:
    if backend == "postgres":
        return """
            CREATE TABLE IF NOT EXISTS interactions (
                id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                query_hash TEXT NOT NULL,
                outcome TEXT,
                timestamp TEXT NOT NULL
            )
        """
    return """
        CREATE TABLE IF NOT EXISTS interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_hash TEXT NOT NULL,
            outcome TEXT,
            timestamp TEXT NOT NULL
        )
    """
