"""The only supported role is a local Spark Connect server. No privilege changes."""
import ipaddress
import json
import os
import signal
import sys
import tempfile
import threading
from pathlib import Path


def load_config(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'duplicate configuration key: {key}')
            result[key] = value
        return result
    try:
        config = json.loads(Path(path).read_text(), object_pairs_hook=unique)
    except (OSError, ValueError) as error:
        raise ValueError(f'cannot read configuration {path}: {error}') from error
    if not isinstance(config, dict) or set(config) != {'bind', 'port', 'allow_unauthenticated_remote'}:
        raise ValueError('configuration requires exactly bind, port, allow_unauthenticated_remote')
    if not isinstance(config['bind'], str):
        raise ValueError('bind must be a literal IP address')
    try:
        address = ipaddress.ip_address(config['bind'])
    except (ValueError, TypeError) as error:
        raise ValueError('bind must be a literal IP address') from error
    if type(config['port']) is not int or not 1024 <= config['port'] <= 65535:
        raise ValueError('port must be an integer between 1024 and 65535')
    if type(config['allow_unauthenticated_remote']) is not bool:
        raise ValueError('allow_unauthenticated_remote must be a boolean')
    if not address.is_loopback and not config['allow_unauthenticated_remote']:
        raise ValueError('non-loopback bind requires allow_unauthenticated_remote=true; Spark Connect has no built-in authentication')
    return config


def validate_runtime(args, environ):
    if args != ['spark-connect']:
        raise ValueError('only the spark-connect role is supported; arbitrary commands/arguments are refused')
    if os.getuid() == 0 or os.geteuid() == 0:
        raise ValueError('Sail must start as non-root')
    if any(key.startswith('SAIL_') and key != 'SAIL_UBI_CONFIG' for key in environ):
        raise ValueError('upstream SAIL_* overrides are unsupported; use SAIL_UBI_CONFIG')
    for directory in ['/tmp', '/var/lib/sail']:
        try:
            with tempfile.TemporaryFile(dir=directory):
                pass
        except OSError as error:
            raise ValueError(f'{directory} must be an explicitly writable mount: {error}') from error


def main():
    try:
        validate_runtime(sys.argv[1:], os.environ)
        config = load_config(os.environ.pop('SAIL_UBI_CONFIG', '/etc/sail/config.json'))
    except ValueError as error:
        print(f'sail-entrypoint: {error}', file=sys.stderr)
        return 64
    if not ipaddress.ip_address(config['bind']).is_loopback:
        print('WARNING: unauthenticated Spark Connect remote binding explicitly enabled; deployment must enforce authentication, TLS and network isolation', file=sys.stderr)
    os.umask(0o077)
    os.chdir('/var/lib/sail')
    os.environ.update(SAIL_MODE='local', SAIL_RUNTIME__TEMPORARY_FILES__PATHS='["/tmp"]',
                      SAIL_EXECUTION__DEFAULT_PARALLELISM='2',
                      SAIL_TELEMETRY__EXPORT_TRACES='false', SAIL_TELEMETRY__EXPORT_METRICS='false',
                      SAIL_TELEMETRY__EXPORT_LOGS='false')
    sys.path.insert(0, '/opt/sail/python')
    sys.argv = ['sail', 'spark', 'server', '--ip', config['bind'], '--port', str(config['port'])]
    # Import/initialize threading on Python's main thread before PyO3 workers
    # can import it during a query (CPython otherwise misidentifies the main thread).
    assert threading.current_thread() is threading.main_thread()
    from pysail.cli import main as serve
    # Let Rust/Tokio own SIGINT; Python would otherwise raise KeyboardInterrupt
    # after the server has already completed its graceful shutdown.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    serve()
    return 0


if __name__ == '__main__':
    sys.exit(main())
