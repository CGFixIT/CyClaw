"""Write operations for the filesystem connector -- fully built, gated, default-off.

Writes are confined to ``writable_roots`` (a SEPARATE list from the read
``allowed_roots``) via the same :class:`agentic.fsconnect.pathsafe.ScopedRoots`
security core, so a write can no more escape its zone than a read can. The connector
is **content-agnostic**: it never calls the LLM; callers supply bytes (e.g. an
operator pipes local-LLM/QWEN output into the CLI).

Gating (the careful guards):

  1. ``writes_enabled`` (config, default False) -- while false, every op returns a
     DRY-RUN plan and nothing is written.
  2. a non-empty human ``reason`` -- required to execute (governance: no anonymous
     mutations), mirroring soul/registry governance.
  3. ``confirm=True`` -- required for DESTRUCTIVE ops (overwrite-existing, move) when
     ``require_confirm_destructive`` is set. New-file writes use ``O_EXCL`` and refuse
     to clobber without ``overwrite``.

``FS_WRITE_HARD_DISABLE`` is a module-level, code-level kill switch (default False):
flip it to True for the most locked-down sites to force dry-run regardless of config.

Never imported by gate.py / graph.py / mcp_hybrid_server.py.
"""

from __future__ import annotations

import hashlib

from agentic.fsconnect.client import build_injection_patterns
from agentic.fsconnect.config import FsConnectConfig
from agentic.fsconnect.pathsafe import ScopedRoots, split_components
from utils.errors import FsWriteRefused
from utils.logger import audit_log

# Code-level kill switch (defense in depth). config.writes_enabled is the operator
# control; setting this True forces dry-run even if config enables writes.
FS_WRITE_HARD_DISABLE = False


class FsWriter:
    """Gated, confined writer bound to a config's ``writable_roots``.

    Use as a context manager so held write-root fds are released.
    """

    def __init__(self, cfg: dict, fs_cfg: FsConnectConfig, config_path: str = "config.yaml") -> None:
        self.cfg = cfg
        self.fs_cfg = fs_cfg
        self.config_path = config_path
        self._roots = ScopedRoots(
            fs_cfg.write_root_strs, create=True, allow_unc=fs_cfg.allow_unc_roots
        )
        self._patterns = build_injection_patterns(cfg) if fs_cfg.scan_content else []

    def close(self) -> None:
        self._roots.close()

    def __enter__(self) -> FsWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- gates ------------------------------------------------------------

    def _executable(self, op: str, reason: str, confirm: bool, *, destructive: bool) -> bool:
        """Return True to execute, False for dry-run. Raise FsWriteRefused on a gate fail."""
        if FS_WRITE_HARD_DISABLE or not self.fs_cfg.writes_enabled:
            return False
        if not (isinstance(reason, str) and reason.strip()):
            raise FsWriteRefused(
                "a non-empty human reason is required to write",
                details={"op": op, "failed_gate": "reason"},
            )
        if destructive and self.fs_cfg.require_confirm_destructive and confirm is not True:
            raise FsWriteRefused(
                "destructive op requires confirm=True",
                details={"op": op, "failed_gate": "confirm"},
            )
        return True

    def _enforce_write_size(self, op: str, data: bytes) -> None:
        """Refuse a write whose payload exceeds ``max_write_bytes``.

        The read path caps bytes via ``pathsafe._read_fd(max_file_bytes)``; the
        write path had no equivalent, so the documented ``max_write_bytes`` cap
        was dead config -- an operator slip or a compromised generate->write
        pipeline could write an arbitrarily large file into a writable root
        (resource exhaustion / disk fill). Mirror the read cap as a hard refusal
        on the execute path, consistent with the reason/confirm gates (only the
        real write is gated; dry-run still returns a plan).
        """
        cap = self.fs_cfg.max_write_bytes
        if len(data) > cap:
            raise FsWriteRefused(
                f"write payload ({len(data)} bytes) exceeds max_write_bytes ({cap})",
                details={"op": op, "failed_gate": "max_write_bytes",
                         "size": len(data), "max": cap},
            )

    def _scan(self, data: bytes) -> list[str]:
        if not self._patterns:
            return []
        text = data.decode("utf-8", errors="replace")
        return [src for src, pat in self._patterns if pat.search(text)]

    def _dryrun(self, op: str, reason: str, extra: dict) -> dict:
        audit_log({"event": "fsconnect_write_dryrun", "op": op, "reason": reason,
                   **{k: v for k, v in extra.items() if isinstance(v, (str, int, bool))}},
                  self.config_path)
        return {"status": "dry_run_plan", "op": op, "executed": False,
                "note": "writes_enabled is false (or hard-disabled); nothing written.",
                "reason": reason, **extra}

    def _audit_applied(self, op: str, reason: str, result: dict, flags: list[str]) -> None:
        audit_log({"event": "fsconnect_write_applied", "op": op, "reason": reason,
                   "path": str(result.get("path") or result.get("to") or result.get("created") or ""),
                   "injection_flag_count": len(flags)}, self.config_path)

    # --- operations -------------------------------------------------------

    def fs_write(
        self, target: str, data: bytes, *, reason: str = "", confirm: bool = False,
        overwrite: bool = False, root: str | None = None,
    ) -> dict:
        split_components(target)            # early path validation (pure)
        self._roots.pick_root(root)         # root must be in the write allow-list
        sha = hashlib.sha256(data).hexdigest()
        extra = {"target": target, "bytes": len(data), "sha256": sha, "overwrite": overwrite}
        if not self._executable("fs_write", reason, confirm, destructive=overwrite):
            return self._dryrun("fs_write", reason, extra)
        self._enforce_write_size("fs_write", data)
        flags = self._scan(data)
        result = self._roots.write_bytes(target, data, root=root, overwrite=overwrite)
        self._audit_applied("fs_write", reason, result, flags)
        return {"status": "applied", "op": "fs_write", "executed": True, "reason": reason,
                "injection_flags": flags, "injection_flag_count": len(flags), **result}

    def fs_append(
        self, target: str, data: bytes, *, reason: str = "", confirm: bool = False,
        root: str | None = None,
    ) -> dict:
        split_components(target)
        self._roots.pick_root(root)
        extra = {"target": target, "bytes": len(data)}
        if not self._executable("fs_append", reason, confirm, destructive=False):
            return self._dryrun("fs_append", reason, extra)
        self._enforce_write_size("fs_append", data)
        flags = self._scan(data)
        result = self._roots.append_bytes(target, data, root=root)
        self._audit_applied("fs_append", reason, result, flags)
        return {"status": "applied", "op": "fs_append", "executed": True, "reason": reason,
                "injection_flags": flags, "injection_flag_count": len(flags), **result}

    def fs_mkdir(
        self, target: str, *, reason: str = "", confirm: bool = False, root: str | None = None,
    ) -> dict:
        split_components(target)
        self._roots.pick_root(root)
        extra = {"target": target}
        if not self._executable("fs_mkdir", reason, confirm, destructive=False):
            return self._dryrun("fs_mkdir", reason, extra)
        result = self._roots.mkdir(target, root=root)
        self._audit_applied("fs_mkdir", reason, result, [])
        return {"status": "applied", "op": "fs_mkdir", "executed": True, "reason": reason, **result}

    def fs_move(
        self, src: str, dst: str, *, reason: str = "", confirm: bool = False,
        overwrite: bool = False, root: str | None = None,
    ) -> dict:
        split_components(src)
        split_components(dst)
        self._roots.pick_root(root)
        extra = {"from": src, "to": dst, "overwrite": overwrite}
        if not self._executable("fs_move", reason, confirm, destructive=True):
            return self._dryrun("fs_move", reason, extra)
        result = self._roots.move(src, dst, root=root, overwrite=overwrite)
        self._audit_applied("fs_move", reason, result, [])
        return {"status": "applied", "op": "fs_move", "executed": True, "reason": reason, **result}


__all__ = ["FsWriter", "FS_WRITE_HARD_DISABLE"]
