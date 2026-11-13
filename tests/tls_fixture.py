"""Per-run PKI and bounded HTTPS REST/S3 protocol fixtures; no new dependencies.

These are transport qualification endpoints, not Lakekeeper/Seaweed emulators.
Only sanitized method/path/TLS/signature outcomes are retained, never keys/headers.
"""
import datetime as dt
import hashlib
import hmac
import io
import json
import re
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, quote, urlsplit

import pyarrow as pa
import pyarrow.parquet as pq
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def pki(root):
    now = dt.datetime.now(dt.timezone.utc)
    issuers = {}
    for name in ('ca', 'wrong-ca'):
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(now + dt.timedelta(hours=24))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False,
                                            key_encipherment=False, data_encipherment=False,
                                            key_agreement=False, key_cert_sign=True, crl_sign=True,
                                            encipher_only=None, decipher_only=None), critical=True)
                .sign(key, hashes.SHA256()))
        (root / f'{name}.crt').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        issuers[name] = (key, cert)
    metadata = []
    for role, hostname in [('proxy', 'localhost'), ('fixture', 'tls-fixture')]:
        for kind in ('valid', 'wrong-san', 'expired', 'wrong-issuer'):
            folder = root / role / kind
            folder.mkdir(parents=True)
            key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
            issuer_key, issuer = issuers['wrong-ca' if kind == 'wrong-issuer' else 'ca']
            san = 'other-service' if kind == 'wrong-san' else hostname
            end = now - dt.timedelta(minutes=1) if kind == 'expired' else now + dt.timedelta(hours=6)
            cert = (x509.CertificateBuilder()
                    .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
                    .issuer_name(issuer.subject).public_key(key.public_key())
                    .serial_number(x509.random_serial_number())
                    .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(end)
                    .add_extension(x509.SubjectAlternativeName([x509.DNSName(san)]), critical=False)
                    .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                    .sign(issuer_key, hashes.SHA256()))
            (folder / 'server.crt').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            (folder / 'server.key').write_bytes(key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            (folder / 'server.key').chmod(0o640)
            metadata.append(dict(role=role, kind=kind, san=san, key_bits=3072,
                                 issuer_sha256=issuer.fingerprint(hashes.SHA256()).hex(),
                                 not_before=(now - dt.timedelta(minutes=5)).isoformat(),
                                 sha256=cert.fingerprint(hashes.SHA256()).hex(), expires=end.isoformat()))
    # CA signing keys only existed in runner memory; never mounted or retained.
    return metadata


class Fixture(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, material, access, secret):
        super().__init__(('0.0.0.0', 0), Handler)
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.minimum_version = ssl.TLSVersion.TLSv1_2
        self.context.load_cert_chain(material / 'server.crt', material / 'server.key')
        self.access, self.secret = access, secret
        self.events = []
        output = io.BytesIO()
        pq.write_table(pa.table({'id': [1, 2, 3], 'label': ['TLS', 'custom CA', 'static credentials']}), output)
        self.parquet = output.getvalue()
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    def get_request(self):
        sock, address = super().get_request()
        sock.settimeout(10)
        try:
            return self.context.wrap_socket(sock, server_side=True), address
        except ssl.SSLError as error:
            self.events.append({'tls_alert': error.reason})
            sock.close()
            raise

    def close(self):
        self.shutdown()
        self.server_close()
        self.thread.join()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def signed(self):
        """Verify actual SigV4 with the per-run static secret, not just key ID."""
        match = re.fullmatch(r'AWS4-HMAC-SHA256 Credential=([^/]+)/([^,]+),\s*SignedHeaders=([^,]+),\s*Signature=([0-9a-f]{64})',
                             self.headers.get('Authorization', ''))
        if not match or self.headers.get('x-amz-security-token'):
            return False
        access, scope, names, signature = match.groups()
        if access != self.server.access:
            return False
        date, region, service, terminator = scope.split('/')
        if region != 'us-east-1' or service != 's3' or terminator != 'aws4_request':
            return False
        url = urlsplit(self.path)
        query = '&'.join(f'{quote(k, safe="-_.~")}={quote(v, safe="-_.~")}' for k, v in sorted(parse_qsl(url.query)))
        headers = ''.join(f'{key}:{" ".join(self.headers[key].split())}\n' for key in names.split(';'))
        canonical = '\n'.join([self.command, url.path, query, headers, names,
                               self.headers.get('x-amz-content-sha256', hashlib.sha256(b'').hexdigest())])
        message = '\n'.join(['AWS4-HMAC-SHA256', self.headers['x-amz-date'], scope,
                             hashlib.sha256(canonical.encode()).hexdigest()])
        key = ('AWS4' + self.server.secret).encode()
        for component in (date, region, service, terminator):
            key = hmac.new(key, component.encode(), hashlib.sha256).digest()
        return hmac.compare_digest(hmac.new(key, message.encode(), hashlib.sha256).hexdigest(), signature)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlsplit(self.path).path
        event = dict(method=self.command, path=path, tls=self.connection.version())
        self.server.events.append(event)
        status = 200
        headers = {}
        if path == '/catalog/v1/config':
            body = json.dumps({'defaults': {}, 'overrides': {}}).encode()
        elif path == '/catalog/v1/namespaces':
            body = json.dumps({'namespaces': [['tls_namespace']]}).encode()
        elif path in ('/qualification/rows.parquet', '/qualification'):
            event['static_sigv4_valid'] = self.signed()
            if not event['static_sigv4_valid']:
                self.send_error(403)
                return
            if path == '/qualification':
                query = dict(parse_qsl(urlsplit(self.path).query))
                if query.get('list-type') != '2' or not 'rows.parquet'.startswith(query.get('prefix', '')):
                    self.send_error(400)
                    return
                body = ('<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                        '<Name>qualification</Name><IsTruncated>false</IsTruncated><KeyCount>1</KeyCount>'
                        '<Contents><Key>rows.parquet</Key><LastModified>2026-01-01T00:00:00.000Z</LastModified>'
                        f'<ETag>"tls-fixture"</ETag><Size>{len(self.server.parquet)}</Size>'
                        '<StorageClass>STANDARD</StorageClass></Contents></ListBucketResult>').encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Content-Type', 'application/xml')
                self.end_headers()
                self.wfile.write(body)
                return
            body = self.server.parquet
            headers = {'ETag': '"tls-fixture"', 'Last-Modified': 'Thu, 01 Jan 2026 00:00:00 GMT',
                       'Accept-Ranges': 'bytes'}
            if self.headers.get('Range'):
                start, end = self.headers['Range'].removeprefix('bytes=').split('-')
                start, end = int(start), int(end) if end else len(body) - 1
                headers['Content-Range'] = f'bytes {start}-{end}/{len(body)}'
                body = body[start:end + 1]
                status = 206
        else:
            self.send_error(404)
            return
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Content-Type', 'application/json' if path.startswith('/catalog/') else 'application/octet-stream')
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)
