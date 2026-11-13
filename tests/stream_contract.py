"""Owner-approved exact-outcome canary and blocking recovery evidence checks."""
RESET_DETAILS = 'Stream removed (RST_STREAM (Received RST_STREAM with error code 2))'
SERVICE = '/spark.connect.SparkConnectService/'


def selected(events, event):
    return [e for e in events if e['event'] == event]


def common(result, mode):
    events = result['events']
    starts = selected(events, 'workload_start')
    assert len(starts) == 1
    assert (starts[0]['rows'], starts[0]['delay'], starts[0]['delayed_batches'],
            starts[0]['retry_mode']) == (1_000_000, 5, 16, mode), starts
    calls = selected(events, 'rpc_start')
    done = selected(events, 'rpc_done')
    assert calls and calls[0]['method'] == SERVICE + 'ExecutePlan'
    assert calls[0]['reattachable'] == [True] and calls[0]['operation_id']
    assert done and (done[0]['method'], done[0]['code'], done[0]['code_number'], done[0]['details']) == (
        SERVICE + 'ExecutePlan', 'INTERNAL', 13, RESET_DETAILS), done
    return events, calls, done


def assert_canary(result):
    if result['returncode'] == 0 or selected(result['events'], 'workload_complete'):
        print('::notice title=Sail paced-stream canary changed::Default-policy stream now succeeds; '
              'review the limitation and update the contract before admission.', flush=True)
        raise AssertionError('unexpected default-policy success; canary requires owner review')
    events, calls, done = common(result, 'default')
    assert result['returncode'] == 1, result['returncode']
    assert len(calls) == len(done) == 1, (calls, done)
    errors = selected(events, 'workload_error')
    assert len(errors) == 1, errors
    error = errors[0]
    assert error['error_type'] == 'SparkConnectGrpcException', error
    assert RESET_DETAILS in error['details'] and 'StatusCode.INTERNAL' in error['details'], error
    assert 70 <= error['elapsed'] <= 90, error
    assert 0 < error['rows'] < 1_000_000 and error['batches'] >= 16, error
    assert calls[0]['seconds'] < done[0]['seconds'], (calls, done)
    return error


def assert_recovery(result):
    events, calls, done = common(result, 'reset')
    assert result['returncode'] == 0 and not selected(events, 'workload_error'), result
    assert len(calls) == len(done) == 2, (calls, done)
    assert calls[1]['method'] == SERVICE + 'ReattachExecute', calls
    assert calls[1]['operation_id'] == calls[0]['operation_id'] and calls[1]['last_response_id'], calls
    assert (done[1]['method'], done[1]['code'], done[1]['code_number'], done[1]['details']) == (
        SERVICE + 'ReattachExecute', 'OK', 0, ''), done
    assert calls[0]['seconds'] < done[0]['seconds'] <= calls[1]['seconds'] < done[1]['seconds'], (calls, done)
    complete = selected(events, 'workload_complete')
    assert len(complete) == 1, complete
    end = complete[0]
    assert (end['rows'], end['unique_ids'], end['payload_hashes_verified'], end['total']) == (
        1_000_000, 1_000_000, 1_000_000, 499_999_500_000), end
    assert end['batches'] >= 16 and end['elapsed'] >= 75, end
    return end
