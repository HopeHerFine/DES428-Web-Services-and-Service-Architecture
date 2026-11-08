"""Local demo switches read from an operator-controlled, read-only mounted file."""
import json
import os
import threading
import time
from pathlib import Path

_lock = threading.Lock()
_revision = None
_seen = set()


def plan():
    path = os.getenv("NOTIFICATIONS_FAULT_FILE")
    if not path:
        return {}
    try:
        config = json.loads(Path(path).read_text())
        if config.get("mode") not in {"none", "slow_calls", "lost_reply", "unavailable"}:
            return {}
        return config
    except (OSError, ValueError):
        return {}


def unavailable(config):
    return config.get("mode") == "unavailable" and time.time() < float(config.get("until", 0))


def take_once(config, key):
    global _revision
    if config.get("mode") not in {"slow_calls", "lost_reply"} or not key:
        return False
    with _lock:
        if _revision != config.get("revision"):
            _seen.clear()
            _revision = config.get("revision")
        if key in _seen:
            return False
        _seen.add(key)
        return True
