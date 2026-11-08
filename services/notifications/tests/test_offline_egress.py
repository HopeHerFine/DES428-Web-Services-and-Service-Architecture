import pytest
from app import offline_workload


def test_offline_claim_is_refused_when_outbound_socket_succeeds(monkeypatch):
    class Connection:
        def close(self):
            pass
    monkeypatch.setattr(offline_workload.socket,'create_connection',lambda *a,**kw:Connection())
    with pytest.raises(RuntimeError,match='outbound connectivity'):
        offline_workload.blocked_egress()


def test_both_outbound_checks_are_required_to_be_blocked(monkeypatch):
    attempted=[]
    def blocked(address,timeout):
        attempted.append(address)
        raise OSError('network unreachable')
    monkeypatch.setattr(offline_workload.socket,'create_connection',blocked)
    offline_workload.blocked_egress()
    assert attempted==[('1.1.1.1',443),('8.8.8.8',53)]
