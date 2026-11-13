#!/usr/bin/env python3
"""One-variable-at-a-time native diagnosis, separate from the blocking TLS gate."""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import tls
from tls_fixture import pki

rt = tls.rt


def experiment(root, nginx, profile, name, rows, delay, delayed_batches):
    pair = tls.start(root, nginx, diagnostic_profile=profile)
    observer = None
    observer_pid = None
    trace_path = tls.EVIDENCE / f'{name}-h2.jsonl'
    try:
        effective = rt.run(rt.RUNTIME, 'exec', pair[1], 'nginx', '-T', '-c', '/etc/nginx/profile/nginx.conf')
        tls.save(name + '-nginx-effective.log', effective.stdout)
        pid = rt.run(rt.RUNTIME, 'inspect', '-f', '{{.State.Pid}}', pair[0]).stdout.strip()
        with trace_path.open('w') as trace:
            observer = subprocess.Popen(['sudo', 'nsenter', '--target', pid, '--net', '/usr/bin/python3', '-u',
                                         str(Path('tests/h2_trace.py').resolve())], stdout=trace, stderr=subprocess.STDOUT)
            for _ in range(50):
                lines = trace_path.read_text().splitlines()
                if lines:
                    first = json.loads(lines[0])
                    assert first['event'] == 'ready', first
                    observer_pid = first['pid']
                    break
                assert observer.poll() is None, 'observer exited before readiness'
                time.sleep(0.1)
            assert observer_pid, 'observer did not start'
            result = rt.run(sys.executable, 'tests/stream_probe.py',
                            f'sc://localhost:{pair[2]}/;use_ssl=true', str(rows), str(delay), str(delayed_batches),
                            env={**os.environ, 'GRPC_DEFAULT_SSL_ROOTS_FILE_PATH': str(root / 'ca.crt')},
                            check=False, timeout=240)
            tls.save(name + '-client.log', result.stdout)
            events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
            assert any(e['event'] in ('workload_error', 'workload_complete') for e in events), result.stdout
            summary = dict(case=name, rows=rows, delay_seconds=delay, delayed_batches=delayed_batches,
                           returncode=result.returncode, events=events)
            tls.save(name + '-result.json', summary)
            print(json.dumps(summary), flush=True)
    finally:
        if observer_pid:
            # Only this observer's reported host PID, never a process-name kill.
            rt.run('sudo', 'kill', '-TERM', str(observer_pid), check=False)
        if observer:
            code = observer.wait(timeout=10)
            tls.save(name + '-observer-status.json', dict(returncode=code))
        tls.stop(pair, name)
    assert code == 0, trace_path.read_text()[-2000:]
    return summary


def main():
    tls.EVIDENCE = Path('evidence/stream-diagnostics')
    tls.EVIDENCE.mkdir(parents=True, exist_ok=True)
    nginx = Path(os.environ['NGINX_SOURCE']).resolve()
    assert rt.run('git', '-C', str(nginx), 'rev-parse', 'HEAD').stdout.strip() == tls.NGINX_COMMIT
    version = rt.run(rt.RUNTIME, 'run', '--rm', '--network', 'none', '--read-only', '--cap-drop=ALL',
                     '--security-opt=no-new-privileges', tls.PROXY, '-V').stdout
    tls.save('nginx-version.log', version)
    rt.run(rt.RUNTIME, 'network', 'create', tls.NETWORK)
    with tempfile.TemporaryDirectory(prefix='sail-stream-diagnostic-') as tmp:
        root = Path(tmp)
        root.chmod(0o755)
        tls.save('certificates.json', pki(root))
        for key in (root / 'proxy').glob('*/server.key'):
            key.chmod(0o440)
            rt.run('sudo', 'chown', '0:0', str(key))
        (root / 'config.json').write_text(json.dumps(dict(bind='127.0.0.1', port=50052,
                                                        allow_unauthenticated_remote=False)))
        original = (nginx / 'examples/profiles/sail/nginx.conf').read_text()
        assert original.count('error_log /dev/stderr notice;') == 1
        profile = root / 'diagnostic.conf'
        profile.write_text(original.replace('error_log /dev/stderr notice;', 'error_log /dev/stderr info;'))
        tls.save('profile-delta.json', {'only_change': 'error_log /dev/stderr notice -> info',
                                      'debug_compiled': '--with-debug' in version})
        results = []
        # Baseline: exact row count/payload and 16 x 5-second pacing of the gate.
        # Every case uses a fresh Sail/proxy pair and a fresh verified-TLS client.
        for name, rows, delay, batches in [('slow-large', 1_000_000, 5, 16),
                                           ('fast-large', 1_000_000, 0, 16),
                                           ('slow-small', 131_072, 5, 16),
                                           ('steady-large', 1_000_000, 0.7, 123)]:
            results.append(experiment(root, nginx, profile, name, rows, delay, batches))
        tls.save('results.json', results)


if __name__ == '__main__':
    try:
        main()
    finally:
        for name in rt.OWNED:
            tls.save(name + '.log', rt.run(rt.RUNTIME, 'logs', name, check=False).stdout)
            rt.run(rt.RUNTIME, 'rm', '-f', name, check=False)
        rt.run(rt.RUNTIME, 'network', 'rm', tls.NETWORK, check=False)
