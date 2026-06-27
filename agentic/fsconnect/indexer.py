"""Toggleable RAG-corpus indexing of the file-share (decoupled, dry-run default).

Indexes ``index_root`` (the file-share, default the first writable root) into
CyClaw's corpus so a generate->write->index loop is possible: the local LLM
generates content, the operator writes it to the share, then -- if ``index_enabled``
is set -- this stages eligible files into the corpus and signals a reindex.

Decoupled to preserve isolation: it enumerates ``index_root`` via the ``pathsafe``
security core, stages eligible files into a corpus subdirectory, and (optionally)
triggers the existing indexer as a SUBPROCESS (``python -m retrieval.indexer``) --
it never imports retrieval/gate/graph/mcp, mirroring how ``sync/`` signals reindex.

Untrusted file content entering the corpus is a real trust boundary, so content is
advisory-injection-scanned during staging (flag surfaced; roadmap: quarantine).

Never imported by gate.py / graph.py / mcp_hybrid_server.py.
"""

from __future__ import annotations

import hashlib
import os
import subprocess  # noqa: S404 -- argv-list reindex trigger only; never shell=True
import sys
from collections.abc import Callable
from pathlib import Path

from agentic.fsconnect.client import build_injection_patterns
from agentic.fsconnect.config import FsConnectConfig
from agentic.fsconnect.pathsafe import ScopedRoots, split_components
from utils.errors import FsConnectError, FsConnectRuntimeError
from utils.logger import audit_log

_DEFAULT_STAGING = Path("data/corpus/fsconnect")


class FsIndexer:
    """Stages eligible file-share content into the corpus and signals reindex."""

    def __init__(self, cfg: dict, fs_cfg: FsConnectConfig, config_path: str = "config.yaml") -> None:
        self.cfg = cfg
        self.fs_cfg = fs_cfg
        self.config_path = config_path
        if not fs_cfg.index_root:
            raise FsConnectError("fsconnect.index_root is not set", code="FSCONNECT_INDEX_ERROR")
        self.index_root = fs_cfg.index_root
        self._patterns = build_injection_patterns(cfg) if fs_cfg.scan_content else []

    def _scan(self, data: bytes) -> int:
        if not self._patterns:
            return 0
        text = data.decode("utf-8", errors="replace")
        return sum(1 for _src, pat in self._patterns if pat.search(text))

    def _walk(
        self,
        roots: ScopedRoots,
        rel: str,
        manifest: list[dict],
        on_file: Callable[[str, bytes], None] | None = None,
    ) -> None:
        for entry in roots.list_dir(rel):
            name = entry["name"]
            child = f"{rel}/{name}" if rel else name
            if entry["type"] == "dir":
                self._walk(roots, child, manifest, on_file)
            elif entry["type"] == "file":
                ext = os.path.splitext(name)[1].lower()
                if ext not in self.fs_cfg.index_extensions:
                    continue
                if entry["size"] > self.fs_cfg.index_max_file_bytes:
                    manifest.append({"path": child, "size": entry["size"], "skipped": "too_large"})
                    continue
                data = roots.read_bytes(child, max_bytes=self.fs_cfg.index_max_file_bytes)
                manifest.append({
                    "path": child, "size": entry["size"],
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "injection_flag_count": self._scan(data),
                })
                # When apply() drives the walk it passes a staging callback so the
                # bytes we just read are written out in the SAME pass. Previously
                # apply() walked to build the manifest (reading every eligible file)
                # and THEN re-read each eligible file from disk a second time -- a
                # second per-component O_NOFOLLOW descent + full read -- purely to
                # fetch bytes the walk had already loaded. One read per file now.
                if on_file is not None:
                    on_file(child, data)

    def scan(self) -> dict:
        """Dry-run: enumerate eligible files under index_root (no copy, no reindex)."""
        manifest: list[dict] = []
        with ScopedRoots([self.index_root], create=True, allow_unc=self.fs_cfg.allow_unc_roots) as roots:
            self._walk(roots, "", manifest)
        eligible = [m for m in manifest if "skipped" not in m]
        audit_log({"event": "fsconnect_index_scan", "index_root": self.index_root,
                   "eligible": len(eligible)}, self.config_path)
        return {"op": "index_scan", "index_root": self.index_root,
                "eligible": len(eligible), "files": manifest}

    def apply(self, *, staging_dir: str | None = None, reindex: bool = False) -> dict:
        """Stage eligible files into the corpus; optionally trigger a reindex subprocess."""
        staging = Path(staging_dir) if staging_dir else _DEFAULT_STAGING
        staging.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        manifest: list[dict] = []

        def _stage(rel: str, data: bytes) -> None:
            # Re-validate the relative path through the same pathsafe guard the
            # read side uses before joining it into the staging dir. A crafted
            # entry name (path separators, "..", drive letter / ADS) must never
            # escape `staging`; this also makes the join correct on Windows,
            # where `rel` is always "/"-separated.
            dest = staging.joinpath(*split_components(rel))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            copied.append(rel)

        with ScopedRoots([self.index_root], create=True, allow_unc=self.fs_cfg.allow_unc_roots) as roots:
            # Single pass: _walk reads each eligible file once and hands the bytes
            # straight to _stage (bounded memory -- one file held at a time).
            self._walk(roots, "", manifest, on_file=_stage)
        audit_log({"event": "fsconnect_index_apply", "index_root": self.index_root,
                   "staged": len(copied), "reindex": reindex}, self.config_path)
        result = {"op": "index_apply", "index_root": self.index_root,
                  "staged": len(copied), "staging_dir": str(staging),
                  "reindex_required": True, "reindexed": False}
        if reindex:
            result["reindexed"] = self._run_reindex()
        return result

    def _run_reindex(self) -> bool:
        """Trigger the existing indexer as a subprocess (decoupled, no import)."""
        try:
            completed = subprocess.run(  # noqa: S603 -- argv list, no shell
                [sys.executable, "-m", "retrieval.indexer"],
                capture_output=True, text=True, timeout=900, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FsConnectRuntimeError("reindex subprocess failed to run",
                                        details={"error": str(exc)}) from exc
        audit_log({"event": "fsconnect_index_reindex", "exit_code": completed.returncode},
                  self.config_path)
        return completed.returncode == 0


__all__ = ["FsIndexer"]
