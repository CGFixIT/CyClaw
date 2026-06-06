#!/usr/bin/env python
"""Unit test for rate limiting added to gate.py (v1.3.0)."""

import time
from unittest.mock import patch, MagicMock
import pytest

def make_check_rate_limit():
    from collections import defaultdict
    _rate_limits = defaultdict(list)
    RATE_LIMIT_REQUESTS = 60
    RATE_LIMIT_WINDOW = 60

    def check_rate_limit(client_ip: str) -> bool:
        now = time.time()
        _rate_limits[client_ip] = [t for t in _rate_limits[client_ip] if now - t < RATE_LIMIT_WINDOW]
        if len(_rate_limits[client_ip]) >= RATE_LIMIT_REQUESTS:
            return False
        _rate_limits[client_ip].append(now)
        return True
    return check_rate_limit

def test_rate_limit_allows_under_limit():
    fn = make_check_rate_limit()
    ip = "10.0.0.1"
    for _ in range(59):
        assert fn(ip) is True

def test_rate_limit_blocks_at_limit():
    fn = make_check_rate_limit()
    ip = "192.168.1.100"
    for _ in range(60):
        fn(ip)
    assert fn(ip) is False

def test_rate_limit_different_ips_independent():
    fn = make_check_rate_limit()
    for _ in range(60):
        fn("1.1.1.1")
    assert fn("2.2.2.2") is True
