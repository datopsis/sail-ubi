"""Passive Linux loopback HTTP/2 observer: retain only control frames and counters.

Run in Sail's network namespace from the CI host, never inside either restricted
container. No capture file, DATA bytes, HPACK headers or TLS/session keys are saved.
"""
import collections
import json
import os
import signal
import socket
import struct
import sys
import time

PREFACE = b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n'
TYPES = {0: 'DATA', 1: 'HEADERS', 2: 'PRIORITY', 3: 'RST_STREAM', 4: 'SETTINGS',
         6: 'PING', 7: 'GOAWAY', 8: 'WINDOW_UPDATE', 9: 'CONTINUATION'}


class Flow:
    def __init__(self, ports, seq, emit):
        self.ports, self.seq, self.emit = ports, seq, emit
        self.pending = {}
        self.buffer = bytearray()
        self.preface = ports[1] == 50052
        self.frames = collections.Counter()
        self.data_bytes = 0
        self.last_data = 0
        self.reset_at = None

    def feed(self, seq, data):
        seq = self.seq + ((seq - self.seq + 2**31) % 2**32 - 2**31)
        end = seq + len(data)
        if end <= self.seq:
            return
        if seq > self.seq:
            self.pending[seq] = data
            return
        self.buffer.extend(data[self.seq - seq:])
        self.seq = end
        self.parse()
        for start in sorted(list(self.pending)):
            if start > self.seq:
                break
            if start in self.pending:
                self.feed(start, self.pending.pop(start))

    def validate_end(self):
        assert not self.pending, 'TCP sequence gap'
        if self.buffer:
            # An observed TCP reset can truncate a DATA frame on the wire. This
            # is transport evidence, not packet loss. Demand a contiguous reset
            # sequence and a valid incomplete DATA header; never decode its body.
            assert self.reset_at == self.seq % 2**32, 'partial frame without contiguous TCP reset'
            assert len(self.buffer) >= 9 and self.buffer[3] == 0, 'truncated control frame'
            length = int.from_bytes(self.buffer[:3], 'big')
            assert len(self.buffer) < length + 9, 'unparsed complete frame'
            self.emit('reset_truncated_data', ports=self.ports, received=len(self.buffer) - 9,
                      expected=length, missing=length + 9 - len(self.buffer))

    def parse(self):
        if self.preface:
            if len(self.buffer) < len(PREFACE):
                return
            assert self.buffer[:len(PREFACE)] == PREFACE, 'missing HTTP/2 preface'
            del self.buffer[:len(PREFACE)]
            self.preface = False
            self.emit('preface', ports=self.ports)
        while len(self.buffer) >= 9:
            length = int.from_bytes(self.buffer[:3], 'big')
            assert length <= 16_777_215
            if len(self.buffer) < length + 9:
                return
            kind, flags = self.buffer[3:5]
            stream = int.from_bytes(self.buffer[5:9], 'big') & 0x7fffffff
            payload = self.buffer[9:9 + length]
            del self.buffer[:9 + length]
            name = TYPES.get(kind, str(kind))
            self.frames[name] += 1
            event = dict(ports=self.ports, frame=name, stream=stream, flags=flags, length=length)
            if kind == 0:
                self.data_bytes += length
                if time.monotonic() - self.last_data >= 5 or flags & 1:
                    self.last_data = time.monotonic()
                    self.emit('data_progress', ports=self.ports, stream=stream,
                              bytes=self.data_bytes, end_stream=bool(flags & 1))
                continue
            if kind == 8:
                # Record counters, not thousands of window increments.
                continue
            if kind == 6:
                event.update(ack=bool(flags & 1), opaque=payload.hex())
            elif kind == 7:
                event.update(last_stream=int.from_bytes(payload[:4], 'big') & 0x7fffffff,
                             error_code=int.from_bytes(payload[4:8], 'big'),
                             debug=bytes(payload[8:]).decode('ascii', errors='replace')[:128])
            elif kind == 3:
                event['error_code'] = int.from_bytes(payload, 'big')
            elif kind == 4:
                event['settings'] = [struct.unpack('!HI', payload[i:i + 6])
                                     for i in range(0, length, 6)]
            elif kind in (1, 9):
                # Headers include SQL/user metadata: do not decode or retain them.
                event['end_stream'] = bool(flags & 1)
            self.emit('frame', **event)


def main():
    running = True
    started = time.monotonic()
    flows = {}

    def emit(event, **fields):
        print(json.dumps(dict(event=event, seconds=time.monotonic() - started,
                              unix_time=time.time(), **fields)), flush=True)

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0800)) as sock:
        try:
            sock.setsockopt(socket.SOL_SOCKET, 33, 16 * 1024 * 1024)  # SO_RCVBUFFORCE, host observer only.
        except PermissionError:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16 * 1024 * 1024)
        sock.bind(('lo', 0))
        sock.settimeout(1)
        emit('ready', pid=os.getpid(), receive_buffer=sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF))
        while running and time.monotonic() - started < 240:
            try:
                packet = sock.recv(262144)
            except socket.timeout:
                continue
            if len(packet) < 54 or packet[12:14] != b'\x08\x00':
                continue
            ip = packet[14:]
            if ip[9] != 6 or ip[12:20] != b'\x7f\x00\x00\x01' * 2:
                continue
            tcp = ip[(ip[0] & 15) * 4:int.from_bytes(ip[2:4], 'big')]
            source, target, seq = struct.unpack('!HHI', tcp[:8])
            if 50052 not in (source, target):
                continue
            ports = (source, target)
            flags = tcp[13]
            if flags & 2:
                flows[ports] = Flow(ports, seq + 1, emit)
                emit('tcp_syn', ports=ports)
            if ports not in flows:
                continue
            payload = tcp[(tcp[12] >> 4) * 4:]
            if payload:
                flows[ports].feed(seq + bool(flags & 2), payload)
            if flags & 4:
                flows[ports].reset_at = seq
            if flags & 5:
                emit('tcp_close', ports=ports, fin=bool(flags & 1), rst=bool(flags & 4))
        packets, drops = struct.unpack('II', sock.getsockopt(263, 6, 8))  # PACKET_STATISTICS
        emit('capture_summary', packets=packets, drops=drops, flows=[
            dict(ports=flow.ports, frames=dict(flow.frames), data_bytes=flow.data_bytes,
                 pending_segments=len(flow.pending), pending_bytes=len(flow.buffer)) for flow in flows.values()])
        assert drops == 0, 'capture dropped packets; frame evidence is incomplete'
        for flow in flows.values():
            flow.validate_end()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps(dict(event='observer_error', error=str(error))), flush=True)
        sys.exit(1)
