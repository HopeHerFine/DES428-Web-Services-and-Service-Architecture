import json
import sys
import pytest
from app import probe_runner


@pytest.mark.parametrize('check', list(probe_runner.CHECKS))
def test_runner_writes_only_matching_probe_result(tmp_path, monkeypatch, check):
    module, arguments, expected = probe_runner.CHECKS[check]
    original = sys.argv
    def run(name, run_name):
        assert name == module and sys.argv == [module, *arguments]
        print('. build/status output is not a result')
        print(json.dumps({'result':'PASS','probe':'some-other-check'}))
        print(json.dumps({'result':'PASS','probe':expected,'checks':[1,2,3]}))
    monkeypatch.setattr(probe_runner.runpy,'run_module',run)
    report = tmp_path/'result.json'
    probe_runner.run_check(check,report)
    assert json.loads(report.read_text())['probe'] == expected
    assert sys.argv is original


@pytest.mark.parametrize('mode', ['failed','missing','duplicate','exception'])
def test_failed_or_ambiguous_probe_never_creates_report(tmp_path, monkeypatch, mode):
    def run(*args, **kwargs):
        if mode == 'exception':
            print('{"result":"PASS","probe":"keycloak-gateway-security"}')
            raise RuntimeError('probe crashed after printing')
        if mode != 'missing':
            print(json.dumps({'result':'FAIL' if mode == 'failed' else 'PASS','probe':'keycloak-gateway-security'}))
        if mode == 'duplicate':
            print('{"result":"PASS","probe":"keycloak-gateway-security"}')
    monkeypatch.setattr(probe_runner.runpy,'run_module',run)
    report = tmp_path/'result.json'
    with pytest.raises(RuntimeError):
        probe_runner.run_check('security',report)
    assert not report.exists()
