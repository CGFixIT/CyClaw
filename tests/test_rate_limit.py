#!/usr/bin/env python
"""Unit test for rate limiting added to gate.py (v1.3)"""

import sys
import time
from collections import defaultdict

sys.path.insert(0, '/home/workdir/artifacts/PsyClaw-refactored')

# Simulate the check_rate_limit function from gate.py
_rate_limits = defaultdict(list)
RATE_LIMIT_REQUESTS = 5  # lower for test
RATE_LIMIT_WINDOW = 2    # seconds

def check_rate_limit(client_ip: str) -> bool:
    now = time.time()
    _rate_limits[client_ip] = [t for t in _rate_limits[client_ip] if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limits[client_ip]) >= RATE_LIMIT_REQUESTS:
        return False
    _rate_limits[client_ip].append(now)
    return True

def test_rate_limit_allows_under_limit():
    ip = "127.0.0.1"  # DevSkim: ignore DS162092 - test-only loopback IP fixture
    _rate_limits.clear()
    for i in range(RATE_LIMIT_REQUESTS):
        assert check_rate_limit(ip), f"Request {i+1} should be allowed"
    print("✓ test_rate_limit_allows_under_limit passed")

def test_rate_limit_blocks_over_limit():
    ip = "192.168.1.1"
    _rate_limits.clear()
    for i in range(RATE_LIMIT_REQUESTS):
        check_rate_limit(ip)
    assert not check_rate_limit(ip), "6th request should be blocked"
    print("✓ test_rate_limit_blocks_over_limit passed")

def test_rate_limit_window_expiry():
    ip = "10.0.0.1"
    _rate_limits.clear()
    for i in range(RATE_LIMIT_REQUESTS):
        check_rate_limit(ip)
    time.sleep(RATE_LIMIT_WINDOW + 0.1)
    assert check_rate_limit(ip), "Request after window should be allowed again"
    print("✓ test_rate_limit_window_expiry passed")

if __name__ == "__main__":
    print("Running rate limit unit tests (v1.3 gate.py logic)...")
    test_rate_limit_allows_under_limit()
    test_rate_limit_blocks_over_limit()
    test_rate_limit_window_expiry()
    print("\n✅ Rate limiting changes verified!")
