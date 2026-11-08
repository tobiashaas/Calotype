"""Well-known Redis list keys (BLPOP/RPUSH)."""

QUEUE_TRAIN = "tarsier:jobs:train"
QUEUE_FEATURE = "tarsier:jobs:feature"
QUEUE_INFERENCE = "tarsier:jobs:inference"
QUEUE_CULL = "tarsier:jobs:cull"


def dlq_name(queue_primary: str) -> str:
    return f"{queue_primary}:dlq"
