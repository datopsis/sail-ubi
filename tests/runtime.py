#!/usr/bin/env python3
"""Native container qualification; retains logs and always removes owned containers."""
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

RUNTIME = os.environ.get('CONTAINER_RUNTIME', 'docker')
IMAGE = os.environ.get('IMAGE', 'localhost/sail-ubi:test')
PREFIX = 'sail-test-' + uuid.uuid4().hex[:10]
OWNED = []
Path('evidence').mkdir(exist_ok=True)


def run(*args, check=True, **kwargs):
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            check=False, timeout=kwargs.pop('timeout', 90), **kwargs)
    if check and result.returncode:
        print(result.stdout, file=sys.stderr, flush=True)
        result.check_returncode()
    return result


def container(name, *args, mounts=True, user=None):
    name = PREFIX + '-' + name
    OWNED.append(name)
    command = [RUNTIME, 'run', '--name', name, '--read-only', '--cap-drop=ALL',
               '--security-opt=no-new-privileges', '--pids-limit=256', '--memory=2g', '--cpus=2']
    if mounts:
        command += ['--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=256m,mode=0700,uid=10001,gid=10001',
                    '--tmpfs', '/var/lib/sail:rw,noexec,nosuid,nodev,size=256m,mode=0700,uid=10001,gid=10001']
    if user:
        command += ['--user', user]
    return name, command + list(args)


def negative(label, expected, options=(), command=(), mounts=True, user=None):
    name, args = container(label, *options, mounts=mounts, user=user)
    result = run(*args, IMAGE, *command, check=False)
    Path(f'evidence/{label}.log').write_text(result.stdout)
    assert result.returncode != 0 and expected in result.stdout, result.stdout
    print(label, 'fails closed:', expected, flush=True)


def ready(name):
    for _ in range(60):
        result = run(RUNTIME, 'exec', name, '/usr/bin/python3.12', '-I', '-B', '/opt/sail/healthcheck.py', check=False)
        if result.returncode == 0:
            return
        if run(RUNTIME, 'inspect', '-f', '{{.State.Running}}', name).stdout.strip() != 'true':
            raise AssertionError(run(RUNTIME, 'logs', name).stdout)
        time.sleep(1)
    raise AssertionError('server did not become ready')


def probe(name):
    result = run(RUNTIME, 'exec', '-i', name, '/usr/bin/python3.12', '-I', '-B', '-', input=Path('tests/probe.py').read_text())
    print(result.stdout, flush=True)
    Path(f'evidence/{name}.json').write_text(result.stdout)


def main():
    metadata = json.loads(run(RUNTIME, 'image', 'inspect', IMAGE).stdout)[0]
    Path('evidence/image-inspect.json').write_text(json.dumps(metadata, indent=2))
    assert metadata['Config']['User'] == '10001:10001'
    assert metadata['Config']['StopSignal'] == 'SIGINT'
    negative('role', 'only the spark-connect role', command=('sh', '-c', 'id'))
    negative('root', 'must start as non-root', user='0:0')
    negative('missing-config', 'cannot read configuration', options=('-e', 'SAIL_UBI_CONFIG=/absent'))
    negative('missing-writes', 'must be an explicitly writable mount', mounts=False)
    negative('unsupported-mode', 'upstream SAIL_* overrides', options=('-e', 'SAIL_MODE=kubernetes-cluster'))
    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / 'config.json'
        # Docker daemon must traverse this host directory for bind mounts.
        Path(tmp).chmod(0o755)
        for label, data, message in [
            ('bad-json', '{', 'cannot read configuration'),
            ('missing-field', '{}', 'configuration requires exactly'),
            ('privileged-port', '{"bind":"127.0.0.1","port":80,"allow_unauthenticated_remote":false}', 'port must be'),
            ('remote-guard', '{"bind":"0.0.0.0","port":50051,"allow_unauthenticated_remote":false}', 'non-loopback bind requires')]:
            if config.exists():
                config.chmod(0o644)
            config.write_text(data)
            config.chmod(0o444)
            negative(label, message, options=('-v', f'{config}:/etc/sail/config.json:ro'))
        name, args = container('default', '-d')
        run(*args, IMAGE)
        ready(name)
        probe(name)
        run(RUNTIME, 'stop', '--time', '20', name)
        assert run(RUNTIME, 'inspect', '-f', '{{.State.ExitCode}}', name).stdout.strip() == '0'
        shutdown_log = run(RUNTIME, 'logs', name).stdout
        assert 'The Spark Connect server has stopped.' in shutdown_log
        assert 'Traceback' not in shutdown_log and 'Exception ignored' not in shutdown_log, shutdown_log
        config.chmod(0o644)
        config.write_text(json.dumps(dict(bind='0.0.0.0', port=50051, allow_unauthenticated_remote=True)))
        name, args = container('query', '-d', '-p', '127.0.0.1::50051', '-v', f'{config}:/etc/sail/config.json:ro')
        run(*args, IMAGE)
        ready(name)
        probe(name)
        port = run(RUNTIME, 'port', name, '50051/tcp').stdout.strip().rsplit(':', 1)[1]
        result = run(sys.executable, 'tests/query.py', f'sc://127.0.0.1:{port}', timeout=180)
        print(result.stdout, flush=True)
        Path('evidence/query.log').write_text(result.stdout)
        probe(name)  # Recheck every process after exercising the query engine.
        assert 'unauthenticated Spark Connect' in run(RUNTIME, 'logs', name).stdout
        run(RUNTIME, 'stop', '--time', '20', name)
        assert run(RUNTIME, 'inspect', '-f', '{{.State.ExitCode}}', name).stdout.strip() == '0'
        shutdown_log = run(RUNTIME, 'logs', name).stdout
        assert 'The Spark Connect server has stopped.' in shutdown_log
        assert 'Traceback' not in shutdown_log and 'Exception ignored' not in shutdown_log, shutdown_log
    print('All restricted native runtime tests passed', flush=True)


if __name__ == '__main__':
    try:
        main()
    finally:
        for name in OWNED:
            result = run(RUNTIME, 'logs', name, check=False)
            Path(f'evidence/{name}.log').write_text(result.stdout)
            run(RUNTIME, 'rm', '-f', name, check=False)
