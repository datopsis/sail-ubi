"""The passive decoder must not invent frames or retain application contents."""
import unittest

from h2_trace import Flow, PREFACE


def frame(kind, payload=b'', flags=0, stream=0):
    return len(payload).to_bytes(3, 'big') + bytes([kind, flags]) + stream.to_bytes(4, 'big') + payload


class TraceTests(unittest.TestCase):
    def test_split_duplicate_and_out_of_order_segments(self):
        events = []
        flow = Flow((1234, 50052), 100, lambda event, **fields: events.append((event, fields)))
        wire = PREFACE + frame(6, b'12345678') + frame(7, b'\0\0\0\x01\0\0\0\x02keep_alive_timeout')
        flow.feed(120, wire[20:])
        flow.feed(100, wire[:10])
        flow.feed(100, wire[:10])
        flow.feed(110, wire[10:20])
        self.assertFalse(flow.pending)
        self.assertFalse(flow.buffer)
        self.assertEqual(flow.frames, {'PING': 1, 'GOAWAY': 1})
        self.assertEqual(events[-1][1]['error_code'], 2)
        self.assertEqual(events[-1][1]['debug'], 'keep_alive_timeout')

    def test_sequence_wrap_and_data_redaction(self):
        events = []
        flow = Flow((50052, 1234), 2**32 - 4, lambda event, **fields: events.append((event, fields)))
        wire = frame(0, b'do-not-retain-this', stream=1) + frame(3, b'\0\0\0\x08', stream=1)
        flow.feed(2**32 - 4, wire[:10])
        flow.feed(6, wire[10:])
        self.assertFalse(flow.buffer)
        self.assertEqual(flow.frames, {'DATA': 1, 'RST_STREAM': 1})
        self.assertEqual(events[-1][1]['error_code'], 8)
        self.assertNotIn('do-not-retain-this', str(events))

    def test_ping_ack_and_headers(self):
        events = []
        flow = Flow((50052, 1234), 1, lambda event, **fields: events.append((event, fields)))
        flow.feed(1, frame(6, b'abcdefgh', flags=1) + frame(1, b'private-header', flags=5, stream=1))
        self.assertTrue(events[0][1]['ack'])
        self.assertTrue(events[1][1]['end_stream'])
        self.assertNotIn('private-header', str(events))

    def test_reset_truncation_requires_contiguous_data(self):
        events = []
        flow = Flow((50052, 1234), 100, lambda event, **fields: events.append((event, fields)))
        flow.feed(100, frame(0, b'private-payload', stream=1)[:12])
        with self.assertRaises(AssertionError):
            flow.validate_end()
        flow.reset_at = 113
        with self.assertRaises(AssertionError):
            flow.validate_end()
        flow.reset_at = 112
        flow.validate_end()
        self.assertEqual(events[-1][0], 'reset_truncated_data')
        self.assertEqual(events[-1][1]['received'], 3)
        self.assertNotIn('private', str(events))
        flow.pending[200] = b'gap'
        with self.assertRaises(AssertionError):
            flow.validate_end()

    def test_multiple_pending_segments(self):
        flow = Flow((50052, 1234), 0, lambda *_a, **_kw: None)
        wire = frame(6, b'12345678')
        flow.feed(10, wire[10:14])
        flow.feed(14, wire[14:])
        flow.feed(0, wire[:10])
        flow.validate_end()
        self.assertEqual(flow.frames, {'PING': 1})
