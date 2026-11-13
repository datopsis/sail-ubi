"""Fresh pinned Spark client process: real operations, never a TLS surrogate."""
import hashlib
import json
import sys
import time

import pyarrow as pa
import pyarrow.compute as pc
from pyspark.sql import SparkSession


def main():
    url, operation = sys.argv[1:]
    spark = SparkSession.builder.remote(url).getOrCreate()
    # Certificate negatives must surface promptly, without a timeout-as-success oracle.
    spark.client.set_retry_policies([])
    try:
        if operation == 'catalog':
            rows = spark.sql('SHOW NAMESPACES IN qualification').collect()
            assert [row.asDict() for row in rows] == [dict(
                name='tls_namespace', catalog='qualification', description=None, locationUri=None)], rows
        elif operation == 's3':
            rows = spark.read.parquet('s3://qualification/rows.parquet').orderBy('id').collect()
            assert [tuple(row) for row in rows] == [(1, 'TLS'), (2, 'custom CA'), (3, 'static credentials')], rows
        else:
            assert spark.sql('SELECT 40 + 2 AS answer').collect()[0].answer == 42
            assert spark.range(100).where('id % 2 = 0').groupBy().sum('id').collect()[0][0] == 2450
            if operation == 'stream':
                frame = spark.range(1_000_000).selectExpr('id', 'sha2(CAST(id AS STRING), 512) AS payload')
                started = time.monotonic()
                batches = count = total = 0
                # Consume Arrow batches directly using the pinned client's iterator;
                # bounded memory and deliberate backpressure over more than a minute.
                try:
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
                            time.sleep(5)
                finally:
                    print(json.dumps(dict(stream_rows_received=count, batches=batches,
                                          seconds=time.monotonic() - started)), flush=True)
                elapsed = time.monotonic() - started
                assert count == 1_000_000 and total == 499_999_500_000
                assert batches >= 16 and elapsed >= 75, (batches, elapsed)
                print(json.dumps(dict(rows=count, sum=total, batches=batches, seconds=elapsed)), flush=True)
        print(f'PASS {operation}', flush=True)
    finally:
        spark.stop()


if __name__ == '__main__':
    main()
