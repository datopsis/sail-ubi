"""Pinned PySpark 4.2.0 policy for Sail 0.7.3's documented proxy reset."""
import grpc
from pyspark.sql.connect.client.retries import RetryPolicy

RESET_DETAILS = 'Stream removed (RST_STREAM (Received RST_STREAM with error code 2))'


class ResetRetry(RetryPolicy):
    def __init__(self):
        # One retry per failed response-read context, with a one-second backoff.
        super().__init__(max_retries=1, initial_backoff=1000, max_backoff=1000)

    def can_retry(self, error):
        return (isinstance(error, grpc.RpcError)
                and error.code() == grpc.StatusCode.INTERNAL
                and error.details() == RESET_DETAILS)
