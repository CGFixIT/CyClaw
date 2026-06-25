"""CyClaw Dropbox corpus sync package.

Out-of-band, rclone-based mirror of a Dropbox folder into the local corpus.
Runs strictly as a separate process (cron / systemd timer / launchd / Task
Scheduler), never imported by gate.py, graph.py, or mcp_hybrid_server.py --
which preserves CyClaw's RAG-first and topology-as-policy invariants by
construction.

Public API:
    from sync import RcloneConfig, load_sync_config, generate_filters, SyncError

Usage from the CLI:
    python -m sync.cli setup
    python -m sync.cli sync [--dry-run]
    python -m sync.cli test
    python -m sync.cli schedule
    python -m sync.cli unschedule
    python -m sync.cli status
"""

from sync.config import RcloneConfig, load_sync_config
from sync.filters import generate_filters, write_filter_file
from utils.errors import (
    RcloneNotInstalledError,
    RcloneTimeoutError,
    RcloneVersionError,
    SchedulerError,
    SyncConfigError,
    SyncError,
    SyncRuntimeError,
)

__all__ = [
    "RcloneConfig",
    "load_sync_config",
    "generate_filters",
    "write_filter_file",
    "SyncError",
    "RcloneNotInstalledError",
    "RcloneTimeoutError",
    "RcloneVersionError",
    "SyncConfigError",
    "SchedulerError",
    "SyncRuntimeError",
]

__version__ = "1.0.0"
