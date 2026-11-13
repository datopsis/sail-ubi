#!/usr/bin/env python3
"""Native shipped-wheel TLS qualification. Any missing assertion fails the job."""
import hashlib
import json
import os
import re
import secrets
import socket
import sys
import tempfile
import time
from pathlib import Path

import runtime as rt
from tls_fixture import Fixture, pki

PROXY = 'localhost/sail-tls-proxy:test'
NGINX_COMMIT = '9ef9e822c6b5e508cebef2adff3bb647a206773c'
RESULTS = []
REDACTIONS = [secrets.token_hex(16), secrets.token_hex(32)]
EVIDENCE = Path('evidence/tls')
NETWORK = rt.PREFIX + '-tls'


def save(name, value):
    text = value if isinstance(value, str) else json.dumps(value, indent=2)
    for secret in REDACTIONS:
        text = text.replace(secret, '[REDACTED]')
    assert not re.search(r'BEGIN .*PRIVATE KEY', text), 'private key in evidence'
    (EVIDENCE / name).write_text(text + '\n')


def passed(edge, case, **details):
    RESULTS.append(dict(edge=edge, case=case, result='PASS', **details))
    save('coverage.json', RESULTS)
    print(json.dumps(RESULTS[-1]), flush=True)


def client(port, operation='query', ca=None, tls=True, label='query', success=True):
    url = f'sc://localhost:{port}' + ('/;use_ssl=true' if tls else '')
    env = {**os.environ, 'GRPC_DEFAULT_SSL_ROOTS_FILE_PATH': str(ca)}
    result = rt.run(sys.executable, 'tests/tls_client.py', url, operation,
                    env=env, timeout=240 if operation == 'stream' else 90, check=False)
    save(label + '-client.log', result.stdout)
    if success:
        assert result.returncode == 0 and f'PASS {operation}' in result.stdout, result.stdout
    else:
        assert result.returncode != 0 and 'PASS ' not in result.stdout, result.stdout
    return result.stdout


def start(root, nginx, kind='valid', ca='ca.crt', endpoint=None, diagnostic_profile=None):
    env = {}
    if diagnostic_profile:
        env['RUST_LOG'] = ('info,hyper::proto::h2=trace,h2::proto::ping_pong=trace,'
                           'h2::proto::connection=debug,h2::proto::streams::state=trace')
    options = ['--network', NETWORK, '--add-host', 'tls-fixture:host-gateway',
               '-p', '127.0.0.1::50051', '-v', f'{root / "config.json"}:/etc/sail/config.json:ro']
    if ca is not None:
        options += ['-v', f'{root / ca}:/run/trust/ca.crt:ro']
        env['SSL_CERT_FILE'] = '/run/trust/ca.crt'
    if endpoint:
        assert endpoint.startswith('https://tls-fixture:')
        env.update(SAIL_CATALOG__LIST='[{type="iceberg-rest", name="qualification", '
                   f'uri="{endpoint}/catalog", warehouse="qualification"}}]',
                   AWS_ENDPOINT=endpoint, AWS_REGION='us-east-1', AWS_ALLOW_HTTP='false',
                   AWS_VIRTUAL_HOSTED_STYLE_REQUEST='false', AWS_EC2_METADATA_DISABLED='true',
                   AWS_ACCESS_KEY_ID=REDACTIONS[0], AWS_SECRET_ACCESS_KEY=REDACTIONS[1])
    # No ambient AWS/profile/trust options enter the Sail container.
    options += [arg for key in env for arg in ('-e', key)]
    sail, command = rt.container('tls-' + secrets.token_hex(4), '-d', *options)
    rt.run(*command, rt.IMAGE, env={**os.environ, **env})
    rt.ready(sail)
    # Existing process, filesystem, capability and sole-listener assertions.
    rt.probe(sail)
    proxy = sail + '-proxy'
    rt.OWNED.append(proxy)
    profile = diagnostic_profile or nginx / 'examples/profiles/sail/nginx.conf'
    rt.run(rt.RUNTIME, 'run', '-d', '--name', proxy, '--network', f'container:{sail}',
           '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
           '--pids-limit=256', '--memory=512m', '--cpus=2', '--user', '10001:0',
           '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777',
           '-v', f'{profile}:/etc/nginx/profile/nginx.conf:ro',
           '-v', f'{root / "proxy" / kind}:/etc/nginx/tls:ro',
           PROXY, '-c', '/etc/nginx/profile/nginx.conf', '-g', 'daemon off;')
    port = int(rt.run(rt.RUNTIME, 'port', sail, '50051/tcp').stdout.strip().rsplit(':', 1)[1])
    for _ in range(60):
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                break
        except OSError:
            time.sleep(0.5)
    else:
        raise AssertionError('proxy readiness failed')
    return sail, proxy, port


def stop(pair, label):
    sail, proxy, _ = pair
    for name, role in [(proxy, 'proxy'), (sail, 'sail')]:
        rt.run(rt.RUNTIME, 'stop', '--time', '20', name)
        logs = rt.run(rt.RUNTIME, 'logs', name).stdout
        assert all(secret not in logs for secret in REDACTIONS), 'credential in server log'
        save(f'{label}-{role}.log', logs)
        assert rt.run(rt.RUNTIME, 'inspect', '-f', '{{.State.ExitCode}}', name).stdout.strip() == '0'
        if role == 'proxy':
            # Recheck Sail after the workload, now the proxy sockets are gone.
            rt.probe(sail)
        rt.run(rt.RUNTIME, 'rm', name)
        rt.OWNED.remove(name)


def isolation(pair):
    sail, proxy, port = pair
    script = '''
import json, os, socket
from pathlib import Path
assert not Path('/etc/nginx/tls/server.key').exists()
listeners = []
for table in ('tcp', 'tcp6'):
    for line in Path('/proc/net/' + table).read_text().splitlines()[1:]:
        fields = line.split()
        if fields[3] == '0A':
            address, port = fields[1].split(':')
            if address != '0B00007F':
                listeners.append((address, int(port, 16)))
assert sorted(listeners) == sorted([
    ('0100007F', 50052), ('00000000', 50051), ('0' * 32, 50051)
]), listeners
for port in (50052, 8080, 8443, 9000):
    s = socket.socket(socket.AF_INET6)
    assert s.connect_ex(('::1', port)) != 0, port
    s.close()
with socket.create_connection(('::1', 50051), timeout=5) as s:
    s.sendall(b'GET / HTTP/1.1\\r\\nHost: localhost\\r\\nConnection: close\\r\\n\\r\\n')
    response = s.recv(8192)
    assert b'400 Bad Request' in response and b'plain HTTP request' in response, response
print(json.dumps(listeners))
'''
    result = rt.run(rt.RUNTIME, 'exec', '-i', sail, '/usr/bin/python3.12', '-I', '-B', '-', input=script)
    save('listeners.json', result.stdout)
    inspect = json.loads(rt.run(rt.RUNTIME, 'inspect', sail, proxy).stdout)
    assert inspect[1]['HostConfig']['NetworkMode'] in ('container:' + sail, 'container:' + inspect[0]['Id'])
    namespaces = [rt.run(rt.RUNTIME, 'exec', name, 'readlink', '/proc/self/ns/net').stdout.strip()
                  for name in (sail, proxy)]
    assert namespaces[0] == namespaces[1], namespaces
    for item in inspect:
        host = item['HostConfig']
        assert host['ReadonlyRootfs'] and host['CapDrop'] == ['ALL']
        assert 'no-new-privileges' in host['SecurityOpt']
        assert host['PidMode'] == '' and host['Privileged'] is False
        assert all(not mount['RW'] for mount in item['Mounts'] if mount['Type'] == 'bind')
    assert not any('AWS_' in entry for entry in inspect[1]['Config']['Env'])
    assert len([m for m in inspect[1]['Mounts'] if m['Type'] == 'bind']) == 2
    address = inspect[0]['NetworkSettings']['Networks'][NETWORK]['IPAddress']
    peer = '''
import socket, sys
address = sys.argv[1]
with socket.create_connection((address, 50051), timeout=5): pass
for port in (50052, 8080, 8443, 9000):
    try:
        with socket.create_connection((address, port), timeout=5): pass
    except ConnectionRefusedError: pass
    else: raise AssertionError(('unexpected listener', port))
print('PASS peer can reach proxy, backend and auxiliary ports refuse connections')
'''
    result = rt.run(rt.RUNTIME, 'run', '--rm', '--network', NETWORK, '--read-only', '--cap-drop=ALL',
                    '--security-opt=no-new-privileges', '--entrypoint', '/usr/bin/python3.12',
                    rt.IMAGE, '-I', '-B', '-c', peer, address)
    save('peer-isolation.log', result.stdout)
    passed('inbound', 'loopback-only backend; IPv4/IPv6 inventory; peer isolation; separate secrets')


def inbound(root, nginx):
    pair = start(root, nginx)
    isolation(pair)
    client(pair[2], ca=root / 'ca.crt', label='inbound-query')
    passed('inbound', 'verified TLS SQL and aggregate')
    for ca, tls, label, pattern in [
        ('wrong-ca.crt', True, 'wrong-ca', r'CERTIFICATE_VERIFY_FAILED|certificate verify failed'),
        ('ca.crt', False, 'plaintext', r'UNAVAILABLE|Socket closed|connection reset|Trying to connect an http1.x server'),
    ]:
        client(pair[2], ca=root / 'ca.crt', label=f'{label}-before')
        output = client(pair[2], ca=root / ca, tls=tls, label=label, success=False)
        assert re.search(pattern, output, re.I), output
        client(pair[2], ca=root / 'ca.crt', label=f'{label}-after')
        passed('inbound', label)
    stop(pair, 'inbound-valid')
    for kind, pattern in [('wrong-san', r'Peer name .* is not in peer certificate|hostname'),
                          ('expired', r'certificate has expired'),
                          ('wrong-issuer', r'CERTIFICATE_VERIFY_FAILED|certificate verify failed')]:
        pair = start(root, nginx, kind)
        output = client(pair[2], ca=root / 'ca.crt', label=kind, success=False)
        assert re.search(pattern, output, re.I), output
        stop(pair, kind)
        pair = start(root, nginx)
        client(pair[2], ca=root / 'ca.crt', label=kind + '-recovery')
        stop(pair, kind + '-recovery')
        passed('inbound', kind)
    # Keep the long stream last so a streaming blocker cannot hide certificate
    # results. The same assertions remain blocking; there is no skip/xfail path.
    pair = start(root, nginx)
    try:
        client(pair[2], 'stream', root / 'ca.crt', label='stream')
        logs = rt.run(rt.RUNTIME, 'logs', pair[1]).stdout
        streams = [json.loads(line) for line in logs.splitlines() if line.startswith('{')]
        streams = [row for row in streams if row['uri'].endswith(('/ExecutePlan', '/ReattachExecute'))
                   and row['request_time'] >= 75 and row['body_bytes_sent'] > 10_000_000]
        assert streams, 'proxy did not observe a long-running result stream'
        assert all(row['protocol'] == 'HTTP/2.0' and row['status'] == 200
                   and row['tls_protocol'] in ('TLSv1.2', 'TLSv1.3') for row in streams), streams
        save('stream-proxy.json', streams)
        passed('inbound', 'paced streaming result')
    except Exception:
        RESULTS.append(dict(edge='inbound', case='paced streaming result', result='FAIL'))
        save('coverage.json', RESULTS)
        # Diagnostic only: run the IDENTICAL workload directly on the existing
        # loopback listener, without publishing it or modifying either image.
        # This cannot satisfy the TLS assertion: the original failure is re-raised.
        pid = rt.run(rt.RUNTIME, 'inspect', '-f', '{{.State.Pid}}', pair[0]).stdout.strip()
        result = rt.run('sudo', '--preserve-env=LD_LIBRARY_PATH', 'nsenter', '--target', pid, '--net',
                        sys.executable, str(Path('tests/tls_client.py').resolve()),
                        'sc://127.0.0.1:50052', 'stream', timeout=240, check=False)
        save('stream-direct-diagnostic.log', result.stdout)
        save('stream-direct-diagnostic.json', dict(returncode=result.returncode,
                                                  note='loopback control only; TLS failure remains blocking'))
        print('Direct loopback stream diagnostic exit:', result.returncode, flush=True)
        raise
    finally:
        stop(pair, 'stream')


def outbound_case(root, nginx, edge, kind='valid', ca='ca.crt', expected=True, label='valid'):
    fixture = Fixture(root / 'fixture' / kind, *REDACTIONS)
    pair = None
    try:
        pair = start(root, nginx, ca=ca, endpoint=f'https://tls-fixture:{fixture.server_port}')
        output = client(pair[2], edge, root / 'ca.crt', label=f'{edge}-{label}', success=expected)
        requests = [event for event in fixture.events if 'method' in event]
        alerts = [event['tls_alert'] for event in fixture.events if 'tls_alert' in event]
        if expected:
            assert requests and all(event['tls'] in ('TLSv1.2', 'TLSv1.3') for event in requests)
            if edge == 'catalog':
                assert any(event['path'] == '/catalog/v1/namespaces' for event in requests), requests
            else:
                assert any(event['method'] == 'GET' and event['static_sigv4_valid'] for event in requests), requests
                assert all(event['static_sigv4_valid'] for event in requests), requests
        else:
            # REST may wrap away reqwest's cause. The originating TLS server must
            # observe a certificate alert AND zero HTTP requests; timeouts/403 fail.
            assert not requests, requests
            assert any(re.search(r'UNKNOWN_CA|BAD_CERTIFICATE|CERTIFICATE_EXPIRED|CERTIFICATE_UNKNOWN', a)
                       for a in alerts), (alerts, output)
            assert re.search(r'certificate|error sending request|TLS|SSL|ConnectError', output, re.I), output
        passed(edge, label, requests=requests, certificate_alerts=alerts)
    finally:
        save(f'{edge}-{label}-endpoint.json', fixture.events)
        fixture.close()
        if pair:
            stop(pair, f'{edge}-{label}')


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    assert json.loads(Path('artifacts/sail.lock.json').read_text())['version'] == '0.7.3'
    nginx = Path(os.environ['NGINX_SOURCE']).resolve()
    assert rt.run('git', '-C', str(nginx), 'rev-parse', 'HEAD').stdout.strip() == NGINX_COMMIT
    proxy = json.loads(rt.run(rt.RUNTIME, 'image', 'inspect', PROXY).stdout)[0]
    assert proxy['Architecture'] == os.environ['ARCHITECTURE']
    assert proxy['Config']['Labels']['org.opencontainers.image.revision'] == NGINX_COMMIT
    lock = nginx / 'artifacts/locks' / (os.environ['ARCHITECTURE'] + '.json')
    assert proxy['Config']['Labels']['io.datopsis.artifact-lock.sha256'] == hashlib.sha256(lock.read_bytes()).hexdigest()
    rt.run(rt.RUNTIME, 'network', 'create', NETWORK)
    with tempfile.TemporaryDirectory(prefix='sail-tls-') as tmp:
        root = Path(tmp)
        root.chmod(0o755)
        save('certificates.json', pki(root))
        # The proxy receives only its root-owned/group-0 private leaf key.
        for key in (root / 'proxy').glob('*/server.key'):
            key.chmod(0o440)
            rt.run('sudo', 'chown', '0:0', str(key))
        (root / 'config.json').write_text(json.dumps(dict(bind='127.0.0.1', port=50052,
                                                        allow_unauthenticated_remote=False)))
        (root / 'malformed.crt').write_text('not a certificate\n')
        # Stop at unsupported shipped-wheel custom trust; no fallback or bypass.
        for edge in ('catalog', 's3'):
            outbound_case(root, nginx, edge)
            for kind, ca, label in [('valid', None, 'missing-ca'), ('valid', 'wrong-ca.crt', 'wrong-ca'),
                                    ('valid', 'malformed.crt', 'malformed-ca'),
                                    ('wrong-issuer', 'ca.crt', 'wrong-issuer'),
                                    ('wrong-san', 'ca.crt', 'wrong-san'), ('expired', 'ca.crt', 'expired')]:
                outbound_case(root, nginx, edge, kind, ca, False, label)
                outbound_case(root, nginx, edge, label=label + '-recovery')
        inbound(root, nginx)
    print('PASS all Phase A Sail TLS assertions', flush=True)


if __name__ == '__main__':
    try:
        main()
    finally:
        for name in rt.OWNED:
            result = rt.run(rt.RUNTIME, 'logs', name, check=False)
            if EVIDENCE.exists():
                save(name + '.log', result.stdout)
            rt.run(rt.RUNTIME, 'rm', '-f', name, check=False)
        rt.run(rt.RUNTIME, 'network', 'rm', NETWORK, check=False)
