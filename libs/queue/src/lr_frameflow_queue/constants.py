"""Well-known Redis list keys (BLPOP/RPUSH)."""

QUEUE_TRAIN = "lrff:jobs:train"
QUEUE_FEATURE = "lrff:jobs:feature"
QUEUE_INFERENCE = "lrff:jobs:inference"
QUEUE_CULL = "lrff:jobs:cull"


def dlq_name(queue_primary: str) -> str:
    return f"{queue_primary}:dlq"
