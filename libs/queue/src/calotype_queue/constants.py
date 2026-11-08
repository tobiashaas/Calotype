"""Well-known Redis list keys (BLPOP/RPUSH)."""

QUEUE_TRAIN = "calotype:jobs:train"
QUEUE_FEATURE = "calotype:jobs:feature"
QUEUE_INFERENCE = "calotype:jobs:inference"
QUEUE_CULL = "calotype:jobs:cull"


def dlq_name(queue_primary: str) -> str:
    return f"{queue_primary}:dlq"
