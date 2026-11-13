"""Real paced workload for the canary, blocking recovery gate and diagnostics."""
import hashlib
import json
import sys
import time
from pathlib import Path

import grpc
import pyarrow as pa
import pyarrow.compute as pc
from pyspark.sql.connect.client import DefaultChannelBuilder
from pyspark.sql.connect.session import SparkSession
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
from spark_connect_retry import ResetRetry

START = time.monotonic()


def emit(event, **fields):
    print(json.dumps(dict(event=event, seconds=time.monotonic() - START,
                         unix_time=time.time(), **fields)), flush=True)


class Observe(grpc.UnaryStreamClientInterceptor):
    def intercept_unary_stream(self, continuation, details, request):
        method = details.method
        options = [option.reattach_options.reattachable for option in getattr(request, 'request_options', [])
                   if option.HasField('reattach_options')]
        emit('rpc_start', method=method, reattachable=options,
             operation_id=getattr(request, 'operation_id', None),
             last_response_id=getattr(request, 'last_response_id', None))
        call = continuation(details, request)
        call.add_done_callback(lambda result: emit('rpc_done', method=method,
                                                   code=result.code().name, code_number=result.code().value[0],
                                                   details=result.details()))
        return call


def main():
    url, size, delay, delayed_batches = sys.argv[1:5]
    retry_mode = sys.argv[5] if len(sys.argv) > 5 else 'none'
    assert retry_mode in ('none', 'default', 'reset')
    size, delay, delayed_batches = int(size), float(delay), int(delayed_batches)
    builder = DefaultChannelBuilder(url)
    assert builder.use_ssl
    builder.add_interceptor(Observe())
    spark = SparkSession.builder.channelBuilder(builder).getOrCreate()
    if retry_mode == 'none':
        spark.client.set_retry_policies([])  # Historical diagnostic control only.
    elif retry_mode == 'reset':
        spark.client.set_retry_policies([ResetRetry()])
    # 'default' deliberately keeps the pinned client's untouched default policy.
    batches = count = total = 0
    seen = bytearray(size)
    started = time.monotonic()
    emit('workload_start', rows=size, delay=delay, delayed_batches=delayed_batches, retry_mode=retry_mode)
    try:
        frame = spark.range(size).selectExpr('id', 'sha2(CAST(id AS STRING), 512) AS payload')
        for table in spark.client.to_table_as_iterator(frame._plan.to_proto(spark.client), {}):
            if not isinstance(table, pa.Table):
                continue
            # Prove the exact ID set without assuming SQL result ordering.
            ids = table['id'].to_pylist()
            for value in ids:
                assert 0 <= value < size and not seen[value], f'duplicate or invalid ID: {value}'
                seen[value] = 1
            batches += 1
            count += table.num_rows
            total += pc.sum(table['id']).as_py()
            expected = pa.array([hashlib.sha512(str(value).encode()).hexdigest()
                                 for value in ids])
            assert table['payload'].null_count == 0, 'null payload'
            assert pc.all(pc.equal(table['payload'], expected)).as_py()
            if batches <= delayed_batches:
                emit('read', batches=batches, rows=count)
                time.sleep(delay)
        assert count == size and total == size * (size - 1) // 2 and all(seen)
        emit('workload_complete', rows=count, batches=batches, total=total,
             unique_ids=sum(seen), payload_hashes_verified=count,
             elapsed=time.monotonic() - started)
    except Exception as error:
        emit('workload_error', rows=count, batches=batches, elapsed=time.monotonic() - started,
             error_type=type(error).__name__, details=str(error))
        raise
    finally:
        spark.stop()


if __name__ == '__main__':
    main()
