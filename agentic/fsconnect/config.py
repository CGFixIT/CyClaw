"""FsConnectConfig dataclass and validating loader for the ``fsconnect:`` block.

Reads the ``fsconnect:`` block from CyClaw's single-source-of-truth ``config.yaml``
via ``utils.logger._get_config`` (shared cached load; tests reset it via
``reset_config_cache``). Purely additive: absence of the block disables the
filesystem connector entirely without perturbing the gateway, graph, or MCP server.

Two independent scopes:
  - ``allowed_roots``   -- READ scope (read-only).
  - ``writable_roots``  -- WRITE scope (a separate list; ``None`` entries expand to an
    OS-appropriate default file-share folder, e.g. ``C:\\CyClaw-FS\\``).

The config validates declared values and computes OS defaults; the actual
``resolve()`` + directory-handle holding happens at runtime in ``pathsafe`` so this
loader stays side-effect free (it never creates directories).

This module is part of a package that is NEVER imported by gate.py, graph.py, or
mcp_hybrid_server.py.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field

from utils.errors import FsConnectConfigError
from utils.logger import _get_config

DEFAULT_ALLOWED_FS_OPS = ("fs_list", "fs_stat", "fs_read", "fs_grep", "fs_glob")
VALID_FS_OPS = frozenset(DEFAULT_ALLOWED_FS_OPS)
DEFAULT_MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MiB
DEFAULT_MAX_WRITE_BYTES = 10 * 1024 * 1024  # 10 MiB
DEFAULT_INDEX_EXTENSIONS = (".md", ".txt", ".pdf", ".docx", ".csv")
DEFAULT_INDEX_MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MiB

_WINDOWS = os.name == "nt"


def os_default_writable_root() -> str:
    """OS-appropriate default for the file-share write root.

    Windows -> ``C:\\CyClaw-FS``. Linux/other -> ``/var/lib/cyclaw-fs`` when
    ``/var/lib`` is writable (service install), else ``~/CyClaw-FS`` (no root
    required). Side-effect free: ``os.access`` probes permission without creating
    anything; the directory itself is created later by ``pathsafe``.
    """
    if _WINDOWS:
        return r"C:\CyClaw-FS"
    if os.access("/var/lib", os.W_OK):
        return "/var/lib/cyclaw-fs"
    return os.path.expanduser("~/CyClaw-FS")


def _is_unc(path: str) -> bool:
    """True if ``path`` looks like a UNC share (``\\\\server\\share`` or ``//server``)."""
    return path.startswith("\\\\") or path.startswith("//")


@dataclass
class FsConnectConfig:
    """Parsed and validated fsconnect: block from config.yaml."""

    # --- read scope ---
    allowed_roots: list[str] = field(default_factory=list)
    allowed_fs_ops: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_FS_OPS))
    allow_unc_roots: bool = False
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    follow_symlinks: bool = False
    scan_content: bool = True
    # --- write scope (separate, gated, default-disabled) ---
    writes_enabled: bool = False
    writable_roots: list[str | None] = field(default_factory=lambda: [None])
    max_write_bytes: int = DEFAULT_MAX_WRITE_BYTES
    require_confirm_destructive: bool = True
    # --- secondary RAG-indexing of the file-share ---
    index_enabled: bool = False
    index_root: str | None = None
    index_extensions: list[str] = field(default_factory=lambda: list(DEFAULT_INDEX_EXTENSIONS))
    index_max_file_bytes: int = DEFAULT_INDEX_MAX_FILE_BYTES
    # When true, apply() skips re-reading/re-staging files whose size+mtime are
    # unchanged since the last run (a skip-cache kept beside the staged files).
    index_incremental: bool = False

    # --- validation -------------------------------------------------------

    def __post_init__(self) -> None:
        self._validate_ops()
        self._validate_caps()
        self._validate_symlinks()
        self._check_root_list("allowed_roots", self.allowed_roots)
        self._normalize_writable_roots()
        self._normalize_index()

    def _validate_ops(self) -> None:
        bad = [op for op in self.allowed_fs_ops if op not in VALID_FS_OPS]
        if bad:
            raise FsConnectConfigError(
                f"fsconnect.allowed_fs_ops contains unknown ops: {bad!r}",
                details={"unknown": bad, "valid": sorted(VALID_FS_OPS)},
            )

    def _validate_caps(self) -> None:
        for name in ("max_file_bytes", "max_write_bytes", "index_max_file_bytes"):
            val = getattr(self, name)
            if not isinstance(val, int) or isinstance(val, bool) or val <= 0:
                raise FsConnectConfigError(
                    f"fsconnect.{name} must be a positive integer, got: {val!r}",
                    details={"field": name, "received": val},
                )

    def _validate_symlinks(self) -> None:
        # v0.1 always denies symlinks/reparse points under a root; an opt-in does
        # not exist yet, so a truthy follow_symlinks is a config error rather than a
        # silent no-op that lulls an operator into thinking links are followed.
        if self.follow_symlinks:
            raise FsConnectConfigError(
                "fsconnect.follow_symlinks must be false in v0.1 (symlinks and "
                "reparse points under a root are always denied; no opt-in exists yet)",
                details={"received": self.follow_symlinks},
            )

    def _check_root_list(self, field_name: str, roots: list[str]) -> None:
        for r in roots:
            if not isinstance(r, str) or not r.strip():
                raise FsConnectConfigError(
                    f"fsconnect.{field_name} entries must be non-empty strings",
                    details={"field": field_name, "received": r},
                )
            if "\x00" in r:
                raise FsConnectConfigError(
                    f"fsconnect.{field_name} entry contains a NUL byte",
                    details={"field": field_name},
                )
            if _is_unc(r) and not self.allow_unc_roots:
                raise FsConnectConfigError(
                    f"fsconnect.{field_name} contains a UNC path but allow_unc_roots is false",
                    details={"field": field_name, "path": r},
                )

    def _normalize_writable_roots(self) -> None:
        # Replace any ``None`` entry with the OS default write root, then validate.
        normalized: list[str] = [
            os_default_writable_root() if r is None else r for r in self.writable_roots
        ]
        self._check_root_list("writable_roots", normalized)
        self.writable_roots = list(normalized)

    def _normalize_index(self) -> None:
        if self.index_root is None:
            # Default the index root to the first writable root (generate->write->index loop).
            write_strs = self.write_root_strs
            self.index_root = write_strs[0] if write_strs else None
        exts: list[str] = []
        for e in self.index_extensions:
            if not isinstance(e, str) or not e.strip():
                raise FsConnectConfigError(
                    "fsconnect.index_extensions entries must be non-empty strings",
                    details={"received": e},
                )
            exts.append((e if e.startswith(".") else "." + e).lower())
        self.index_extensions = exts

    # --- computed ---------------------------------------------------------

    @property
    def write_root_strs(self) -> list[str]:
        """Writable roots as concrete strings (``None`` already normalized away)."""
        return [r for r in self.writable_roots if isinstance(r, str)]

    def to_dict(self) -> dict:
        return asdict(self)


def load_fsconnect_config(config_path: str = "config.yaml") -> FsConnectConfig:
    """Read config.yaml's fsconnect: block and return a validated FsConnectConfig.

    Raises ``FsConnectConfigError`` if the block is absent, malformed, or any value
    fails validation. ``enabled`` is read out as a plain attribute (default False --
    the connector is conservatively opt-in) and enforced by the CLI. Unknown keys
    are collected on a non-fatal ``_unknown_keys`` attribute for typo visibility.
    """
    cfg = _get_config(config_path) or {}

    block = cfg.get("fsconnect")
    if not block:
        raise FsConnectConfigError(
            "fsconnect: block missing from config.yaml",
            details={
                "hint": "Append the fsconnect: block to config.yaml. "
                "See agentic/fsconnect/config.py for the schema."
            },
        )
    if not isinstance(block, dict):
        raise FsConnectConfigError(
            f"fsconnect: block must be a mapping, got {type(block).__name__}",
            details={"received_type": type(block).__name__},
        )

    known_fields = set(FsConnectConfig.__dataclass_fields__)
    unknown = set(block.keys()) - known_fields
    unknown.discard("enabled")  # CyClaw's own on/off toggle, not a config field
    kwargs = {k: v for k, v in block.items() if k in known_fields}

    try:
        fc = FsConnectConfig(**kwargs)
    except TypeError as exc:
        raise FsConnectConfigError(
            f"fsconnect: block invalid: {exc}",
            details={"unknown_keys": sorted(unknown)},
        ) from exc

    fc.enabled = bool(block.get("enabled", False))  # type: ignore[attr-defined]
    fc._unknown_keys = sorted(unknown)  # type: ignore[attr-defined]
    return fc
