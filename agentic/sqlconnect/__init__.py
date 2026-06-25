"""CyClaw read-only SQL connector -- out-of-band, disabled-by-default scaffold.

A pre-committed scaffold for read-only on-prem SQL (Postgres / MSSQL). Disabled by
default; absence of the ``sqlconnect:`` block or ``enabled: false`` is a pure no-op
with no effect on existing functionality. Read-only is enforced at the session level
and by a SELECT-only query guard; the DSN is read from an environment variable only.
Runs strictly via ``python -m agentic.sqlconnect.cli`` and is NEVER imported by
gate.py / graph.py / mcp_hybrid_server.py.

Public API:
    from agentic.sqlconnect import SqlConnectConfig, load_sqlconnect_config
"""

from agentic.sqlconnect.config import SqlConnectConfig, load_sqlconnect_config
from utils.errors import (
    SqlConnectConfigError,
    SqlConnectError,
    SqlConnectRuntimeError,
    SqlDriverNotInstalledError,
)

__all__ = [
    "SqlConnectConfig",
    "load_sqlconnect_config",
    "SqlConnectError",
    "SqlConnectConfigError",
    "SqlConnectRuntimeError",
    "SqlDriverNotInstalledError",
]

__version__ = "0.1.0"
