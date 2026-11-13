"""Reject plausible false-positive canaries and incomplete/reexecuted recoveries."""
import copy
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from stream_contract import RESET_DETAILS, SERVICE, assert_canary, assert_recovery


def result(recovery=False):
    events = [dict(event='workload_start', rows=1_000_000, delay=5, delayed_batches=16,
                   retry_mode='reset' if recovery else 'default'),
              dict(event='rpc_start', method=SERVICE + 'ExecutePlan', seconds=0.1,
                   reattachable=[True], operation_id='operation', last_response_id=None),
              dict(event='rpc_done', method=SERVICE + 'ExecutePlan', seconds=80.2,
                   code='INTERNAL', code_number=13, details=RESET_DETAILS)]
    if recovery:
        events += [dict(event='rpc_start', method=SERVICE + 'ReattachExecute', seconds=81.2,
                        operation_id='operation', last_response_id='cursor'),
                   dict(event='rpc_done', method=SERVICE + 'ReattachExecute', seconds=83,
                        code='OK', code_number=0, details=''),
                   dict(event='workload_complete', rows=1_000_000, batches=123, elapsed=83,
                        unique_ids=1_000_000, payload_hashes_verified=1_000_000, total=499_999_500_000)]
    else:
        events.append(dict(event='workload_error', error_type='SparkConnectGrpcException',
                           details='StatusCode.INTERNAL: ' + RESET_DETAILS,
                           elapsed=80.2, rows=163_840, batches=20))
    return dict(returncode=0 if recovery else 1, events=events)


class StreamContractTests(unittest.TestCase):
    def test_expected_failure_and_complete_recovery(self):
        assert_canary(result())
        assert_recovery(result(True))

    def test_canary_rejects_other_errors_timing_and_client_modes(self):
        for index, key, value in [(0, 'retry_mode', 'none'), (2, 'code', 'UNAVAILABLE'),
                                  (2, 'code_number', 14), (2, 'details', 'different INTERNAL error'),
                                  (3, 'error_type', 'TimeoutExpired'), (3, 'error_type', 'AssertionError'),
                                  (3, 'elapsed', 69.9), (3, 'elapsed', 90.1),
                                  (3, 'rows', 0), (3, 'rows', 1_000_000), (3, 'batches', 0)]:
            with self.subTest(index=index, key=key, value=value):
                changed = result()
                changed['events'][index][key] = value
                with self.assertRaises(AssertionError):
                    assert_canary(changed)
        changed = result()
        changed['returncode'] = -9
        with self.assertRaises(AssertionError):
            assert_canary(changed)

    def test_unexpected_success_is_visible_and_blocks(self):
        for changed in [dict(returncode=0, events=[]), result()]:
            if changed['events']:
                changed['events'].append(dict(event='workload_complete'))
            output = io.StringIO()
            with redirect_stdout(output), self.assertRaises(AssertionError):
                assert_canary(changed)
            self.assertIn('::notice title=Sail paced-stream canary changed::', output.getvalue())

    def test_recovery_requires_cursor_same_operation_and_exact_data(self):
        for index, key, value in [(0, 'retry_mode', 'default'), (3, 'method', SERVICE + 'ExecutePlan'),
                                  (3, 'operation_id', 'new-operation'), (3, 'last_response_id', ''),
                                  (3, 'seconds', 70), (4, 'code', 'INTERNAL'),
                                  (5, 'rows', 999_999), (5, 'unique_ids', 999_999),
                                  (5, 'payload_hashes_verified', 999_999), (5, 'total', 0)]:
            with self.subTest(index=index, key=key, value=value):
                changed = result(True)
                changed['events'][index][key] = value
                with self.assertRaises(AssertionError):
                    assert_recovery(changed)
        changed = result(True)
        changed['events'].insert(4, copy.deepcopy(changed['events'][3]))
        with self.assertRaises(AssertionError):
            assert_recovery(changed)

    def test_documented_policy_is_the_tested_example(self):
        policy = Path('examples/spark_connect_retry.py').read_text().strip()
        self.assertIn('```python\n' + policy + '\n```', Path('docs/TLS.md').read_text())
