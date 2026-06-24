"""Thread-safe rate limiter with optional sqlite persistence.

Extracted from ``gate.py`` so the limiter is a single importable unit shared
by the FastAPI gateway and its tests.

Default mode (db_path=None): pure in-memory (original behavior, fast for tests).
Persistent mode (db_path="data/rate_limits.db"): state survives restarts.

The gateway calls ``allow()`` from FastAPI's threadpool, so we keep the
threading.Lock for the hot path. When persistence is enabled we also write
through to sqlite under the same lock (simple but correct).

Behavior preserved:
  * 60 requests / 60-second sliding window per client IP (configurable).
  * Idle-IP eviction.
  * Injectable clock for deterministic tests.

Hardened in feature/CyClaw-Agent: optional sqlite persistence so rate state
survives container/process restarts (in-memory died on restart).
"""

import json
import logging
import sqlite3
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class RateLimiter:
    """Fixed-window-ish sliding rate limiter, safe under concurrent threads.

    When db_path is provided, hits are persisted to sqlite so the limiter
    survives restarts (key hardening request for the agentic branch).
    """

    def __init__(
        self,
        max_requests: int = 60,
        window_seconds: float = 60,
        clock: Callable[[], float] = time.time,
        db_path: Optional[str] = None,   # NEW: set to "data/rate_limits.db" for persistence
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clock = clock
        self._db_path = db_path
        self._hits: Dict[str, List[float]] = defaultdict(list)
        self._last_sweep = 0.0
        self._lock = threading.Lock()

        if self._db_path:
            self._init_db()
            self._load_from_db()

    def _init_db(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rate_hits (
                    ip TEXT PRIMARY KEY,
                    timestamps TEXT NOT NULL,
                    last_sweep REAL NOT NULL
                )
            """)
            conn.commit()

    def _load_from_db(self) -> None:
        if not self._db_path:
            return
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute("SELECT ip, timestamps, last_sweep FROM rate_hits").fetchall()
            for ip, ts_json, last_sweep in rows:
                try:
                    self._hits[ip] = json.loads(ts_json)
                except (json.JSONDecodeError, TypeError, ValueError):
                    # Corrupt/garbled persisted window (e.g. truncated write from a
                    # prior crash). Dropping it silently erased an IP's live rate
                    # limit on every restart with no trace; log it so the state
                    # loss is auditable rather than invisible. Recover gracefully
                    # by resetting just this IP's window to empty.
                    logger.warning(
                        "Rate-limit state for IP %s is corrupt; resetting its window to empty", ip
                    )
                    self._hits[ip] = []
                self._last_sweep = max(self._last_sweep, last_sweep or 0.0)

    def _persist(self, client_ip: str, now: float) -> None:
        """Persist a single IP's window to sqlite.

        Caller must hold ``self._lock``. Only the IP touched by the current
        ``allow()`` call is written — previously this rewrote the ENTIRE IP map
        on every request, turning each request into O(N) row writes (N = tracked
        IPs) plus a connection open/close. Under load that was severe write
        amplification; one INSERT OR REPLACE for the touched IP is O(1).
        """
        if not self._db_path:
            return
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO rate_hits (ip, timestamps, last_sweep) VALUES (?, ?, ?)",
                (client_ip, json.dumps(self._hits[client_ip]), now),
            )
            conn.commit()

    def _sweep(self, now: float) -> None:
        """Evict clients whose timestamps are all outside the window.

        Caller must hold ``self._lock``. Runs at most once per window so the
        hot path stays cheap.
        """
        if now - self._last_sweep < self.window_seconds:
            return
        self._last_sweep = now
        stale = [
            ip for ip, hits in self._hits.items()
            if all(now - t >= self.window_seconds for t in hits)
        ]
        for ip in stale:
            del self._hits[ip]

    def allow(self, client_ip: str) -> bool:
        """Return True if the request is within the limit, else False.

        The entire read-modify-write is performed under the lock.
        When persistence is enabled we also flush to sqlite under the same lock.
        """
        now = self._clock()
        with self._lock:
            self._sweep(now)
            recent = [t for t in self._hits[client_ip] if now - t < self.window_seconds]
            if len(recent) >= self.max_requests:
                self._hits[client_ip] = recent
                self._persist(client_ip, now)
                return False
            recent.append(now)
            self._hits[client_ip] = recent
            self._persist(client_ip, now)
            return True

    def tracked_ips(self) -> int:
        """Number of IPs currently held in the map (for eviction tests/metrics)."""
        with self._lock:
            return len(self._hits)
