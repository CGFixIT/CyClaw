"""RcloneConfig dataclass and validating loader for the CyClaw sync: block.

Reads the ``sync:`` block from CyClaw's single-source-of-truth ``config.yaml``
via ``utils.logger._get_config`` (so it shares the same cached load and the same
``reset_config_cache`` test hook). Purely additive: absence of the block disables
sync entirely without perturbing the gateway or indexer.

Hardened defaults (conservative, in line with CyClaw's offline-first /
soul-governance posture):

  - direction:        "pull"      one-way Dropbox -> local; bisync is opt-in
  - include_soul:     False       data/personality/ NOT synced by default
  - max_delete:       20          safety fuse: rclone aborts if > N deletions
  - conflict_resolve: "newer"     bisync only -- newer modtime wins
  - conflict_loser:   "rename"    bisync only -- loser saved as .conflict1

To change defaults, edit the sync: block in config.yaml -- never edit this file
unless you are changing the schema itself.
"""

from __future__ import annotations

import os
import platform
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from utils.errors import SyncConfigError
from utils.logger import _get_config

# Defaults -- every key here can be overridden by config.yaml.
DEFAULT_REMOTE_NAME = "dropbox_cyclaw"
DEFAULT_REMOTE_PATH = "CyClaw/corpus"
DEFAULT_DIRECTION = "pull"  # "pull" (safe default) | "bisync" (opt-in)
DEFAULT_SCHEDULE_HOUR = 2
DEFAULT_SCHEDULE_MIN = 0
DEFAULT_MAX_DELETE = 20
DEFAULT_MAX_TRANSFER = "1G"
DEFAULT_CONFLICT_RESOLVE = "newer"
DEFAULT_CONFLICT_LOSER = "rename"
DEFAULT_INCLUDE_SOUL = False
DEFAULT_REINDEX_ON_CHANGE = True  # exit 10 if corpus files changed
DEFAULT_CHECKSUM = True

# Validation constants.
_REMOTE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
# Shell metacharacters that must never appear in remote_path (defense in depth;
# we never use shell=True, but reject taint at the boundary anyway).
_SHELL_METACHARS = set(";|&$`<>(){}[]!*?\"'\\\n\r\t ")
_VALID_DIRECTIONS = ("pull", "bisync")
_VALID_CONFLICT_RESOLVE = ("newer", "older", "larger", "smaller", "none")


def _default_rclone_state_dir() -> Path:
    """Return rclone's state directory, honouring XDG_CONFIG_HOME."""
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "rclone"
    return Path.home() / ".config" / "rclone"


@dataclass
class RcloneConfig:
    """Parsed and validated sync: block from config.yaml."""

    # Required (validated: absolute, under repo data/corpus tree).
    local_path: str

    # Remote identity (rclone remote name and path inside Dropbox).
    remote_name: str = DEFAULT_REMOTE_NAME
    remote_path: str = DEFAULT_REMOTE_PATH

    # Sync behaviour.
    direction: str = DEFAULT_DIRECTION  # "pull" | "bisync"
    include_soul: bool = DEFAULT_INCLUDE_SOUL
    reindex_on_change: bool = DEFAULT_REINDEX_ON_CHANGE
    checksum: bool = DEFAULT_CHECKSUM

    # Safety fuses.
    max_delete: int = DEFAULT_MAX_DELETE
    max_transfer: str = DEFAULT_MAX_TRANSFER

    # bisync-only knobs (ignored when direction == "pull").
    conflict_resolve: str = DEFAULT_CONFLICT_RESOLVE
    conflict_loser: str = DEFAULT_CONFLICT_LOSER

    # Scheduling (cron / systemd / launchd / Task Scheduler).
    schedule_hour: int = DEFAULT_SCHEDULE_HOUR
    schedule_min: int = DEFAULT_SCHEDULE_MIN

    # File locations (defaults computed at load time, all overridable).
    workdir: str | None = None  # bisync state dir
    filter_file: str | None = None  # cyclaw_filters.txt path
    log_dir: str | None = None  # rclone log dir

    # Extra exclusions appended AFTER the built-in hardened defaults.
    extra_excludes: list[str] = field(default_factory=list)

    # Reindex exit code -- caller uses this to detect "corpus changed".
    REINDEX_EXIT_CODE: int = 10

    # --- Validation -------------------------------------------------------

    def __post_init__(self) -> None:
        self._validate_local_path()
        self._validate_remote_name()
        self._validate_remote_path()

        if self.direction not in _VALID_DIRECTIONS:
            raise SyncConfigError(
                f"sync.direction must be 'pull' or 'bisync', got: {self.direction!r}",
                details={"received": self.direction},
            )

        if self.max_delete < 0:
            raise SyncConfigError(
                f"sync.max_delete must be >= 0, got: {self.max_delete}",
                details={"received": self.max_delete},
            )

        if not 0 <= self.schedule_hour <= 23:
            raise SyncConfigError(
                f"sync.schedule_hour must be 0-23, got: {self.schedule_hour}",
                details={"received": self.schedule_hour},
            )

        if not 0 <= self.schedule_min <= 59:
            raise SyncConfigError(
                f"sync.schedule_min must be 0-59, got: {self.schedule_min}",
                details={"received": self.schedule_min},
            )

        if self.conflict_resolve not in _VALID_CONFLICT_RESOLVE:
            raise SyncConfigError(
                f"sync.conflict_resolve invalid: {self.conflict_resolve!r}",
                details={"valid": list(_VALID_CONFLICT_RESOLVE)},
            )

        self._fill_default_paths()

    def _validate_local_path(self) -> None:
        if not self.local_path:
            raise SyncConfigError(
                "sync.local_path is required",
                details={"hint": "Set sync.local_path to a path under the repo's data/corpus tree."},
            )

        # Expand ~ and env vars early so downstream code does not have to.
        expanded = os.path.expanduser(os.path.expandvars(self.local_path))

        # A relative default like "data/corpus" is resolved against the repo
        # root (cwd) into an absolute path; an already-absolute path is kept.
        resolved = Path(expanded).resolve()

        # Repo root is two levels up from this file: sync/config.py -> repo/.
        repo_root = Path(__file__).resolve().parent.parent
        corpus_root = (repo_root / "data" / "corpus").resolve()

        # Must resolve to corpus_root itself or a path inside it. resolve()
        # collapses ".." and follows symlinks, so an escape via ".." or a
        # symlink cannot land inside corpus_root.
        if resolved != corpus_root and corpus_root not in resolved.parents:
            raise SyncConfigError(
                "sync.local_path must resolve to a path inside the repo's data/corpus tree",
                details={"resolved": str(resolved), "corpus_root": str(corpus_root)},
            )

        # After resolution, store an absolute path so callers never see a
        # relative value or an unresolved "..".
        self.local_path = str(resolved)

    def _validate_remote_name(self) -> None:
        if not _REMOTE_NAME_RE.match(self.remote_name):
            raise SyncConfigError(
                f"sync.remote_name must match ^[A-Za-z0-9_.-]+$, got: {self.remote_name!r}",
                details={"received": self.remote_name},
            )

    def _validate_remote_path(self) -> None:
        if self.remote_path.startswith("-"):
            raise SyncConfigError(
                f"sync.remote_path must not start with '-' (would be parsed as a flag): {self.remote_path!r}",
                details={"received": self.remote_path},
            )
        bad = sorted(_SHELL_METACHARS & set(self.remote_path))
        if bad:
            raise SyncConfigError(
                f"sync.remote_path contains forbidden characters: {bad!r}",
                details={"received": self.remote_path, "forbidden": bad},
            )

    def _fill_default_paths(self) -> None:
        state_dir = _default_rclone_state_dir()
        if self.workdir is None:
            self.workdir = str(state_dir / "bisync_state")
        if self.filter_file is None:
            self.filter_file = str(state_dir / "cyclaw_filters.txt")
        if self.log_dir is None:
            self.log_dir = str(state_dir / "logs")

        self.workdir = os.path.expanduser(os.path.expandvars(self.workdir))
        self.filter_file = os.path.expanduser(os.path.expandvars(self.filter_file))
        self.log_dir = os.path.expanduser(os.path.expandvars(self.log_dir))

    # --- Computed properties ---------------------------------------------

    @property
    def remote(self) -> str:
        """Combined remote spec for rclone, e.g. 'dropbox_cyclaw:CyClaw/corpus'."""
        return f"{self.remote_name}:{self.remote_path}"

    @property
    def log_path(self) -> str:
        """Full path to the active rclone log file."""
        return os.path.join(self.log_dir or "", "rclone_cyclaw.log")

    @property
    def is_windows(self) -> bool:
        return platform.system() == "Windows"

    # --- Serialization ---------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)


def load_sync_config(config_path: str = "config.yaml") -> RcloneConfig:
    """Read config.yaml's sync: block and return a validated RcloneConfig.

    Loads through ``utils.logger._get_config`` (cached; tests reset via
    ``reset_config_cache``). Raises ``SyncConfigError`` if the block is absent,
    malformed, or any value fails validation. Unknown keys are collected on a
    non-fatal ``_unknown_keys`` attribute for typo visibility.
    """
    cfg = _get_config(config_path) or {}

    block = cfg.get("sync")
    if not block:
        raise SyncConfigError(
            "sync: block missing from config.yaml",
            details={
                "hint": "Append the sync: block to config.yaml. "
                "See docs/SYNC_README.md or sync/config.py for the schema."
            },
        )

    if not isinstance(block, dict):
        raise SyncConfigError(
            f"sync: block must be a mapping, got {type(block).__name__}",
            details={"received_type": type(block).__name__},
        )

    # Pass through only fields RcloneConfig knows about (excluding the constant
    # REINDEX_EXIT_CODE). Unknown keys are collected, not fatal.
    known_fields = {f for f in RcloneConfig.__dataclass_fields__ if f != "REINDEX_EXIT_CODE"}
    unknown = set(block.keys()) - known_fields
    # "enabled" is CyClaw's own on/off toggle, not an rclone parameter, so it is
    # not an RcloneConfig field and not a typo. It is read out here and enforced
    # by the CLI (``cmd_sync`` no-ops when false); drop it from the unknown set.
    unknown.discard("enabled")
    kwargs = {k: v for k, v in block.items() if k in known_fields}

    try:
        rc = RcloneConfig(**kwargs)
    except TypeError as exc:
        raise SyncConfigError(
            f"sync: block invalid: {exc}",
            details={"unknown_keys": sorted(unknown)},
        ) from exc

    # Default to enabled when the key is absent (a present sync: block is opt-in
    # already). Stored as a plain attribute, not a dataclass field, to keep it
    # out of the rclone-parameter surface (to_dict / argv).
    rc.enabled = bool(block.get("enabled", True))  # type: ignore[attr-defined]
    rc._unknown_keys = sorted(unknown)  # type: ignore[attr-defined]
    return rc
