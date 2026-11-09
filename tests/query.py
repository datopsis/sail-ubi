"""Real Spark Connect protocol, SQL/DataFrame execution and writable data path."""
import sys
from pyspark.sql import SparkSession

spark = SparkSession.builder.remote(sys.argv[1]).getOrCreate()
try:
    assert spark.sql('SELECT 40 + 2 AS answer').collect()[0].answer == 42
    assert spark.range(100).where('id % 2 = 0').groupBy().sum('id').collect()[0][0] == 2450
    spark.range(5).write.mode('overwrite').parquet('/var/lib/sail/smoke.parquet')
    assert spark.read.parquet('/var/lib/sail/smoke.parquet').count() == 5
    print('Spark Connect SQL, DataFrame aggregate, Parquet write/read: PASS', flush=True)
finally:
    spark.stop()
