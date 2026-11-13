"""Diagnostic workload; never replaces or relaxes tests/tls_client.py's gate."""
import hashlib
import json
import sys
import time

import grpc
import pyarrow as pa
import pyarrow.compute as pc
from pyspark.sql.connect.client import DefaultChannelBuilder
from pyspark.sql.connect.session import SparkSession

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
             operation_id=getattr(request, 'operation_id', None))
        call = continuation(details, request)
        call.add_done_callback(lambda result: emit('rpc_done', method=method,
                                                   code=result.code().name, details=result.details()))
        return call


def main():
    url, size, delay = sys.argv[1:]
    size, delay = int(size), float(delay)
    builder = DefaultChannelBuilder(url)
    assert builder.use_ssl
    builder.add_interceptor(Observe())
    spark = SparkSession.builder.channelBuilder(builder).getOrCreate()
    spark.client.set_retry_policies([])  # Same policy as the blocking workload.
    batches = count = total = 0
    started = time.monotonic()
    emit('workload_start', rows=size, delay=delay, delayed_batches=16)
    try:
        frame = spark.range(size).selectExpr('id', 'sha2(CAST(id AS STRING), 512) AS payload')
        for table in spark.client.to_table_as_iterator(frame._plan.to_proto(spark.client), {}):
            if not isinstance(table, pa.Table):
                continue
            batches += 1
            count += table.num_rows
            total += pc.sum(table['id']).as_py()
            expected = pa.array([hashlib.sha512(str(value).encode()).hexdigest()
                                 for value in table['id'].to_pylist()])
            assert pc.all(pc.equal(table['payload'], expected)).as_py()
            if batches <= 16:
                emit('read', batches=batches, rows=count)
                time.sleep(delay)
        assert count == size and total == size * (size - 1) // 2
        emit('workload_complete', rows=count, batches=batches, elapsed=time.monotonic() - started)
    except Exception as error:
        emit('workload_error', rows=count, batches=batches, elapsed=time.monotonic() - started,
             error_type=type(error).__name__, details=str(error))
        raise
    finally:
        spark.stop()


if __name__ == '__main__':
    main()
