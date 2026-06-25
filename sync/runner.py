"""rclone subprocess wrapper for CyClaw corpus sync.

Responsibilities:
  - Locate and version-check the rclone binary (floor 1.68.2 -- CVE-2024-52522).
  - Build the right argv for pull (``rclone copy``) or bisync (``rclone bisync``).
  - Run rclone with a structured log file.
  - Parse the log to derive per-file events (added / modified / deleted).
  - Hash each touched file under data/corpus/ with SHA-256 for audit.
  - Emit audit events via ``utils.logger.audit_log``.
  - Decide whether to signal "corpus changed -> reindex" via exit code.

This module does NOT import anything from gate.py, graph.py, or the FastAPI /
MCP layer. It runs strictly out-of-band and writes only to the local filesystem
and the audit log. That isolation is what keeps CyClaw's five security
invariants intact: it cannot bypass retrieval, alter graph topology, or modify
soul state (soul is excluded by default -- see filters.py).

argv is ALWAYS a list and rclone is ALWAYS resolved to an absolute path via
``shutil.which`` -- never ``shell=True``, never a string command. Every argv
element comes from validated config plus a fixed flag list, so there is no taint
path into the subprocess.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import re
import shutil
import subprocess  # noqa: S404 -- argv-list rclone invocation only; never shell=True (see run_sync)
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from sync.config import RcloneConfig
from sync.filters import write_filter_file
from utils.errors import (
    RcloneNotInstalledError,
    RcloneTimeoutError,
    RcloneVersionError,
    SyncRuntimeError,
)
from utils.logger import audit_log

# ---------------------------------------------------------------------------
# Version handling
# ---------------------------------------------------------------------------

MIN_RCLONE_MAJOR, MIN_RCLONE_MINOR, MIN_RCLONE_PATCH = 1, 68, 2

_RCLONE_VERSION_RE = re.compile(r"rclone\s+v?(\d+)\.(\d+)(?:\.(\d+))?", re.IGNORECASE)


def check_rclone_version(rclone_bin: str = "rclone") -> tuple[int, int, int]:
    """Confirm rclone is installed and >= 1.68.2.

    Returns the parsed ``(major, minor, patch)`` tuple. Raises
    ``RcloneNotInstalledError`` if the binary is not on PATH, or
    ``RcloneVersionError`` if the version is too old (CVE-2024-52522 floor).
    """
    binary = shutil.which(rclone_bin)
    if binary is None:
        raise RcloneNotInstalledError(
            "rclone binary not found on PATH",
            details={
                "looked_for": rclone_bin,
                "install_hint_linux": "curl https://rclone.org/install.sh | sudo bash",
                "install_hint_windows": "winget install Rclone.Rclone",
            },
        )

    try:
        # argv list; binary is an absolute path from shutil.which; no shell.
        result = subprocess.run(  # noqa: S603 -- argv list, absolute binary, no shell
            [binary, "version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        # rclone is installed (shutil.which succeeded) but hung on "rclone version";
        # this is an environment stall, not a missing binary.
        raise RcloneTimeoutError(
            f"rclone version check timed out: {exc}",
            details={"binary": binary},
        ) from exc

    output = (result.stdout or "") + (result.stderr or "")
    match = _RCLONE_VERSION_RE.search(output)
    if not match:
        raise RcloneVersionError(
            "Could not parse rclone version output",
            details={"binary": binary, "output": output[:500]},
        )

    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3)) if match.group(3) else 0

    if (major, minor, patch) < (MIN_RCLONE_MAJOR, MIN_RCLONE_MINOR, MIN_RCLONE_PATCH):
        raise RcloneVersionError(
            f"rclone {major}.{minor}.{patch} is too old; need >= "
            f"{MIN_RCLONE_MAJOR}.{MIN_RCLONE_MINOR}.{MIN_RCLONE_PATCH} "
            "(CVE-2024-52522 fix)",
            details={
                "found": f"{major}.{minor}.{patch}",
                "required": f">={MIN_RCLONE_MAJOR}.{MIN_RCLONE_MINOR}.{MIN_RCLONE_PATCH}",
                "binary": binary,
            },
        )

    return (major, minor, patch)


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

# rclone's default log verbs are stable; we anchor on the trailing verb only:
#   2026/05/21 02:10:01 INFO  : file.md: Copied (new)
#   2026/05/21 02:10:01 INFO  : file.md: Copied (replaced existing)
#   2026/05/21 02:10:01 INFO  : file.md: Deleted
_LOG_ADDED_RE = re.compile(r":\s*([^:]+?):\s*Copied\s*\(new\)", re.IGNORECASE)
_LOG_MODIFIED_RE = re.compile(
    r":\s*([^:]+?):\s*(?:Copied \(replaced existing\)|Updated modification time)",
    re.IGNORECASE,
)
_LOG_DELETED_RE = re.compile(r":\s*([^:]+?):\s*Deleted(?:\s|$)", re.IGNORECASE)
_LOG_ERROR_RE = re.compile(r"\bERROR\b\s*:\s*(.+)", re.IGNORECASE)

# rclone's own scratch / state artifacts that may appear in a log line but are
# NOT corpus content. They should never trip the "corpus changed -> reindex"
# signal even if one ever leaks past the filter file.
_RCLONE_INTERNAL_PREFIXES = (".rclone-", "bisync-", ".tmp-", "RCLONE_TEST")


def _is_rclone_internal(path: str) -> bool:
    """True if any component of *path* is an rclone scratch/state artifact.

    rclone logs paths relative to the transfer root, usually flat ("notes.md")
    but occasionally nested ("sub/.rclone-cache/x"). A plain
    ``path.startswith(_RCLONE_INTERNAL_PREFIXES)`` only catches root-level
    artifacts, so a nested scratch file would slip through and wrongly trip the
    "corpus changed -> reindex" signal. Inspect every path component instead.
    Backslashes are normalised so a Windows-style log path is handled too.
    """
    return any(
        part.startswith(_RCLONE_INTERNAL_PREFIXES)
        for part in path.replace("\\", "/").split("/")
        if part
    )


@dataclass
class FileEvent:
    """A single per-file event derived from the rclone log."""

    kind: str  # "added" | "modified" | "deleted"
    path: str  # path relative to the local repo root
    sha256: str | None = None  # populated by hash_changed_files(); None for deletions

    def to_audit_dict(self, base: str) -> dict:
        # Use a "file" key, never "query": audit_log() SHA-256-hashes any field
        # named "query" and we want this path to stay human-readable.
        return {
            "event": f"sync_file_{self.kind}",
            "file": self.path,
            "sha256": self.sha256 or "",
            "base": base,
        }


@dataclass
class SyncResult:
    """Outcome of a single sync run."""

    success: bool
    direction: str  # "pull" | "bisync" | "dry-run"
    started_at: float  # epoch seconds
    finished_at: float  # epoch seconds
    rclone_exit_code: int
    events: list[FileEvent] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    log_path: str | None = None
    aborted_for_safety: bool = False  # True if --max-delete / --max-transfer tripped
    dry_run: bool = False
    corpus_changed: bool = False  # True if any event hit data/corpus/**

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.finished_at - self.started_at)

    def event_counts(self) -> dict:
        counts = {"added": 0, "modified": 0, "deleted": 0}
        for ev in self.events:
            counts[ev.kind] = counts.get(ev.kind, 0) + 1
        return counts

    def to_audit_dict(self) -> dict:
        return {
            "event": "sync_completed" if self.success else "sync_failed",
            "direction": self.direction,
            "duration_sec": round(self.duration_sec, 3),
            "rclone_exit_code": self.rclone_exit_code,
            "counts": self.event_counts(),
            "errors_n": len(self.errors),
            "aborted_for_safety": self.aborted_for_safety,
            "dry_run": self.dry_run,
            "corpus_changed": self.corpus_changed,
        }


def parse_log(log_path: str) -> tuple[list[FileEvent], list[str]]:
    """Parse an rclone log file into ``(events, errors)``.

    Tolerant: any line that does not match a known pattern is ignored. Errors
    are captured as raw strings.

    Scope note: the regexes target the ``rclone copy`` execution verbs
    (``Copied (new)``, ``Copied (replaced existing)``, ``Deleted``). ``rclone
    bisync`` also emits these verbs during its execution phase, so deletions and
    copies are still captured for bisync. Its *pre-sync* structured-diff lines
    (``- Path1   File is new   - file.md``) are intentionally not parsed: bisync
    is opt-in/discouraged here, and the execution-phase verbs are sufficient to
    derive ``corpus_changed``. Per-file event counts for bisync may therefore be
    a lower bound; rely on the run's exit status, not the count, for bisync.
    """
    events: list[FileEvent] = []
    errors: list[str] = []

    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _LOG_ADDED_RE.search(line)
                if m:
                    events.append(FileEvent(kind="added", path=m.group(1).strip()))
                    continue
                m = _LOG_MODIFIED_RE.search(line)
                if m:
                    events.append(FileEvent(kind="modified", path=m.group(1).strip()))
                    continue
                m = _LOG_DELETED_RE.search(line)
                if m:
                    events.append(FileEvent(kind="deleted", path=m.group(1).strip()))
                    continue
                m = _LOG_ERROR_RE.search(line)
                if m:
                    errors.append(m.group(1).strip())
    except FileNotFoundError:
        # No log file == nothing happened. Caller decides whether that is an error.
        pass

    # Dedupe by (kind, path), preserving first-seen order. With --checksum on the
    # default pull path, rclone can emit both a "Copied (replaced existing)" line
    # and a separate "Updated modification time" line for the same file -- both
    # match _LOG_MODIFIED_RE. Without dedup that double-counts `modified` in
    # event_counts() and makes hash_changed_files() SHA the same path twice.
    seen: set[tuple[str, str]] = set()
    deduped: list[FileEvent] = []
    for ev in events:
        key = (ev.kind, ev.path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ev)

    return deduped, errors


def hash_changed_files(events: Sequence[FileEvent], local_root: str) -> list[FileEvent]:
    """Populate ``FileEvent.sha256`` for added/modified entries still on disk.

    Deleted files keep ``sha256=None`` (the bytes are gone -- nothing to hash).
    Files missing from disk are also left as ``None``. Hashing is streamed in
    64 KiB chunks with stdlib ``hashlib.sha256``. Returns a NEW list; the input
    is untouched.
    """
    out: list[FileEvent] = []
    for ev in events:
        if ev.kind == "deleted":
            out.append(ev)
            continue
        abs_path = os.path.join(local_root, ev.path)
        try:
            with open(abs_path, "rb") as f:
                h = hashlib.sha256()
                for chunk in iter(lambda f=f: f.read(65536), b""):
                    h.update(chunk)
                out.append(dataclasses.replace(ev, sha256=h.hexdigest()))
        except OSError:
            out.append(ev)
    return out


# ---------------------------------------------------------------------------
# Argv builders -- always lists; every element is a fixed flag or validated cfg.
# ---------------------------------------------------------------------------

def _common_args(cfg: RcloneConfig, log_path: str) -> list[str]:
    """Args shared between ``copy`` and ``bisync``.

    Note: ``--max-delete`` is intentionally excluded here. ``rclone copy``
    never deletes destination files, so the flag would be a no-op for pull
    mode. It is added only in ``build_bisync_argv`` where deletions can occur.
    """
    args: list[str] = [
        "--filter-from", cfg.filter_file,
        f"--max-transfer={cfg.max_transfer}",
        "--check-first",
        "--log-file", log_path,
        "--log-level", "INFO",
    ]
    if cfg.checksum:
        args.append("--checksum")
    return args


def build_pull_argv(
    cfg: RcloneConfig,
    dry_run: bool,
    log_path: str,
    rclone_bin: str = "rclone",
) -> list[str]:
    """Argv for one-way pull (Dropbox -> local). ``rclone copy`` never deletes."""
    argv = [
        rclone_bin, "copy",
        cfg.remote, cfg.local_path,
        *_common_args(cfg, log_path),
    ]
    if dry_run:
        argv.append("--dry-run")
    return argv


def build_bisync_argv(
    cfg: RcloneConfig,
    dry_run: bool,
    log_path: str,
    resync: bool = False,
    rclone_bin: str = "rclone",
) -> list[str]:
    """Argv for bidirectional ``bisync`` (opt-in, discouraged)."""
    argv = [
        rclone_bin, "bisync",
        cfg.remote, cfg.local_path,
        f"--conflict-resolve={cfg.conflict_resolve}",
        f"--conflict-loser={cfg.conflict_loser}",
        "--workdir", cfg.workdir,
        f"--max-delete={cfg.max_delete}",  # only meaningful where deletions occur
        *_common_args(cfg, log_path),
    ]
    if resync:
        argv.append("--resync")
    if dry_run:
        argv.append("--dry-run")
    return argv


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _detect_safety_abort(errors: Sequence[str], stderr: str) -> bool:
    """True if rclone tripped the --max-delete or --max-transfer safety fuse."""
    haystacks = list(errors) + [stderr or ""]
    return any(
        ("max-delete" in h.lower() or "max-transfer" in h.lower())
        for h in haystacks
    )


# A daily scheduled run and a manual run must never drive rclone against the
# same remote/destination at once: their log writes would interleave and corrupt
# parsing, and concurrent filter-file writes would race. ``os.mkdir`` is atomic
# on every platform, so it doubles as a zero-dependency, cross-platform lock --
# no fcntl/msvcrt branching, no third-party dep.
_LOCK_STALE_SEC = 3 * 60 * 60  # reclaim a lock left by a crashed run after 3h


def _acquire_sync_lock(lock_dir: str) -> None:
    """Acquire the single-instance lock, or raise ``SyncRuntimeError``.

    Reclaims a lock older than ``_LOCK_STALE_SEC`` (a prior run that crashed
    without releasing it) so a stale directory can never wedge sync forever.
    """
    try:
        os.mkdir(lock_dir)
        return
    except FileExistsError:
        pass
    try:
        age = time.time() - os.path.getmtime(lock_dir)
    except OSError:
        age = 0.0
    if age > _LOCK_STALE_SEC:
        try:
            os.rmdir(lock_dir)
            os.mkdir(lock_dir)
            return
        except OSError:
            pass
    raise SyncRuntimeError(
        "Another CyClaw sync appears to be running",
        details={
            "lock_dir": lock_dir,
            "hint": "Wait for the other run to finish, or remove the lock dir if it is stale.",
        },
    )


def _release_sync_lock(lock_dir: str) -> None:
    """Release the single-instance lock; tolerant if it is already gone."""
    try:
        os.rmdir(lock_dir)
    except OSError:
        pass


def run_sync(
    cfg: RcloneConfig,
    dry_run: bool = False,
    resync: bool = False,
    rclone_bin: str = "rclone",
) -> SyncResult:
    """Execute one sync run end-to-end.

    1. Confirm rclone is installed and recent enough (>= 1.68.2).
    2. (Re)write the rclone filter file.
    3. Build argv for pull or bisync.
    4. Run rclone, capturing exit code and the log file.
    5. Parse the log into FileEvents.
    6. Hash any added/modified files under data/corpus/ for the audit row.
    7. Emit audit events: sync_started, sync_file_*, sync_completed | sync_failed.
    8. Return a SyncResult.

    Raises ``RcloneNotInstalledError`` / ``RcloneVersionError`` on environment
    failure, ``SyncRuntimeError`` on unexpected subprocess failure. Normal rclone
    non-zero exits (e.g. a tripped safety fuse) do NOT raise -- they return a
    ``SyncResult`` with ``success=False`` and ``aborted_for_safety=True`` so the
    caller can react cleanly.

    Security: argv is a list, the binary is absolute, ``shell`` is never set, and
    only metadata is logged -- never raw stderr that could echo a token.

    Concurrency: a process-wide single-instance lock (an atomically created lock
    directory under ``log_dir``) prevents a manual run and the scheduled run from
    driving rclone against the same remote at once. A second concurrent run
    raises ``SyncRuntimeError``; a lock left by a crashed run is reclaimed after
    ``_LOCK_STALE_SEC``.
    """
    check_rclone_version(rclone_bin)

    os.makedirs(cfg.log_dir or ".", exist_ok=True)
    lock_dir = os.path.join(cfg.log_dir or ".", "sync.lock.d")
    _acquire_sync_lock(lock_dir)
    try:
        return _run_sync_locked(cfg, dry_run, resync, rclone_bin)
    finally:
        _release_sync_lock(lock_dir)


def _run_sync_locked(
    cfg: RcloneConfig,
    dry_run: bool,
    resync: bool,
    rclone_bin: str,
) -> SyncResult:
    """Body of ``run_sync`` executed while holding the single-instance lock."""
    write_filter_file(cfg)

    log_path = cfg.log_path
    # Clear the previous run's log so parsing sees ONLY this run's lines. rclone
    # opens --log-file in append mode, so a stale log left in place would be
    # re-parsed in full -- replaying a previous run's FileEvents and ERROR lines
    # and potentially raising a false safety-abort. Truncate (open "w") rather
    # than unlink: it still clears the file when the inode cannot be removed but
    # is writable, and it leaves an empty file for rclone to append to. The
    # single-instance lock guarantees no concurrent writer, so if we cannot
    # produce a clean log we fail loudly instead of silently parsing stale data.
    try:
        with open(log_path, "w", encoding="utf-8"):
            pass
    except OSError as exc:
        raise SyncRuntimeError(
            "could not clear previous rclone log before sync",
            details={"direction": cfg.direction},
        ) from exc

    if cfg.direction == "bisync":
        argv = build_bisync_argv(
            cfg, dry_run=dry_run, log_path=log_path, resync=resync, rclone_bin=rclone_bin
        )
    else:
        argv = build_pull_argv(cfg, dry_run=dry_run, log_path=log_path, rclone_bin=rclone_bin)

    started_at = time.time()
    audit_log({
        "event": "sync_started",
        "direction": cfg.direction,
        "dry_run": dry_run,
        "remote": cfg.remote,
        "local_path": cfg.local_path,
        "include_soul": cfg.include_soul,
    })

    # A 0 timeout means "unbounded" (subprocess.run treats timeout=None that way).
    run_timeout = cfg.sync_timeout_sec if cfg.sync_timeout_sec > 0 else None
    try:
        # argv is a list of a fixed flag set + validated config; never shell=True.
        completed = subprocess.run(  # noqa: S603 -- argv list, validated inputs, no shell
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=run_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        # rclone hung past the wall-clock ceiling. subprocess.run has already
        # killed the child and reaped it by the time TimeoutExpired propagates,
        # so the single-instance lock is released cleanly when we raise. Do not
        # echo argv (it carries the remote spec) — surface only the direction and
        # the limit that tripped.
        raise SyncRuntimeError(
            f"rclone sync timed out after {cfg.sync_timeout_sec}s",
            details={"direction": cfg.direction, "timeout_sec": cfg.sync_timeout_sec},
        ) from exc
    except FileNotFoundError as exc:
        # rclone disappeared between the version check and now (race). Do not
        # include argv (would leak the remote spec into the error string).
        raise RcloneNotInstalledError(
            "rclone binary disappeared during execution",
            details={"direction": cfg.direction},
        ) from exc
    except subprocess.SubprocessError as exc:
        raise SyncRuntimeError(
            f"rclone subprocess failed: {type(exc).__name__}",
            details={"direction": cfg.direction},
        ) from exc

    finished_at = time.time()
    exit_code = completed.returncode

    # Parse log -> events -> hash -> audit.
    events, errors = parse_log(log_path)
    events = hash_changed_files(events, cfg.local_path)

    aborted_for_safety = _detect_safety_abort(errors, completed.stderr or "")

    # rclone logs file paths RELATIVE TO THE TRANSFER ROOT (the destination
    # directory), not relative to the repo root -- e.g. "notes.md", never
    # "data/corpus/notes.md". Since cfg.local_path is validated to resolve under
    # data/corpus (RcloneConfig.__post_init__), every parsed file event is by
    # construction a corpus change. We still defensively skip rclone's own
    # scratch/state artifacts in case one ever slips past the filter file.
    corpus_changed = any(not _is_rclone_internal(ev.path) for ev in events)

    result = SyncResult(
        success=(exit_code == 0),
        direction=("dry-run" if dry_run else cfg.direction),
        started_at=started_at,
        finished_at=finished_at,
        rclone_exit_code=exit_code,
        events=events,
        errors=errors,
        log_path=log_path,
        aborted_for_safety=aborted_for_safety,
        dry_run=dry_run,
        corpus_changed=corpus_changed,
    )

    # Per-file audit events -- one row per file, with sha256 when available.
    for ev in events:
        audit_log(ev.to_audit_dict(base=cfg.local_path))

    # Summary audit event -- sync_completed (success) or sync_failed (otherwise).
    audit_log(result.to_audit_dict())

    return result


def reindex_exit_code_for(result: SyncResult, cfg: RcloneConfig) -> int:
    """Return the CLI exit code to use after a sync run.

    0   -- sync OK, no corpus change (or reindex_on_change disabled).
    10  -- sync OK, corpus changed; caller should run ``python -m retrieval.indexer``.
    1   -- sync failed for safety reasons (--max-delete / --max-transfer tripped).
    2   -- sync failed for any other reason.
    """
    if not result.success:
        return 1 if result.aborted_for_safety else 2
    if cfg.reindex_on_change and result.corpus_changed:
        return cfg.REINDEX_EXIT_CODE
    return 0
