"""TCP liveness only; tests prove the Spark Connect query path separately."""
import json
import os
import socket
from pathlib import Path

config = json.loads(Path(os.environ.get('SAIL_UBI_CONFIG', '/etc/sail/config.json')).read_text())
address = {'0.0.0.0': '127.0.0.1', '::': '::1'}.get(config['bind'], config['bind'])
with socket.create_connection((address, config['port']), timeout=3):
    pass
