import json
import time

from app import faults


def test_flags_default_off_and_do_not_allow_repeated_delay_for_same_write(tmp_path, monkeypatch):
    monkeypatch.delenv("NOTIFICATIONS_FAULT_FILE", raising=False)
    assert faults.plan() == {}
    path = tmp_path / "faults.json"
    monkeypatch.setenv("NOTIFICATIONS_FAULT_FILE", str(path))
    assert faults.plan() == {}
    path.write_text(json.dumps({"mode": "slow_calls", "revision": "unit-slow-1"}))
    plan = faults.plan()
    assert faults.take_once(plan, "same-key") is True
    assert faults.take_once(plan, "same-key") is False
    assert faults.take_once({**plan, "revision": "unit-slow-2"}, "same-key") is True
    assert faults.take_once(plan, None) is False


def test_outage_expires_and_unknown_configuration_is_disabled(tmp_path, monkeypatch):
    assert faults.unavailable({"mode": "unavailable", "until": time.time() + 5})
    assert not faults.unavailable({"mode": "unavailable", "until": time.time() - 1})
    path = tmp_path / "faults.json"
    monkeypatch.setenv("NOTIFICATIONS_FAULT_FILE", str(path))
    path.write_text('{"mode":"unknown"}')
    assert faults.plan() == {}
    path.write_text('broken json')
    assert faults.plan() == {}
