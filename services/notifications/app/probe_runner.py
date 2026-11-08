"""Run an operator probe and write only its validated result to a report file."""
import argparse
import contextlib
import io
import json
import runpy
import sys

CHECKS = {
    'security': ('app.security_probe', [], 'keycloak-gateway-security'),
    'resilience': ('app.resilience_fixture', ['verify'], 'notifications-resilience'),
    'recovery': ('app.broker_recovery', ['verify-outbox'], 'broker-worker-recovery'),
    'observability': ('app.observability_probe', [], 'observability'),
}


def run_check(check, report):
    module, arguments, expected = CHECKS[check]
    captured = io.StringIO()
    previous = sys.argv
    try:
        sys.argv = [module, *arguments]
        with contextlib.redirect_stdout(captured):
            runpy.run_module(module, run_name='__main__')
    finally:
        sys.argv = previous
        print(captured.getvalue(), end='')
    candidates = []
    for line in captured.getvalue().splitlines():
        try:
            result = json.loads(line)
        except ValueError:
            continue
        if isinstance(result, dict) and result.get('probe') == expected:
            candidates.append(result)
    if len(candidates) != 1 or candidates[0].get('result') != 'PASS':
        raise RuntimeError('Probe did not produce exactly one matching PASS result')
    # Exclusive create prevents accidental reuse of an earlier report.
    with open(report, 'x', encoding='utf-8') as destination:
        json.dump(candidates[0], destination)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('check', choices=CHECKS)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    run_check(args.check, args.report)


if __name__ == '__main__':
    main()
