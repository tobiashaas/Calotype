from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from botocore.client import BaseClient
from sqlalchemy.orm import Session

from calotype_api.storage import get_s3_client
from calotype_persistence.session import get_session_factory, session_scope
from calotype_queue.publisher import RedisQueuePublisher, redis_from_env


@lru_cache(maxsize=1)
def session_factory_holder():
    return get_session_factory()


def get_session() -> Generator[Session, None, None]:
    factory = session_factory_holder()
    with session_scope(factory) as session:
        yield session


def get_publisher() -> RedisQueuePublisher:
    # Not cached intentionally to respect env mocks in tests; cheap construction.
    return RedisQueuePublisher(redis_from_env())


def get_storage() -> BaseClient:
    # Not cached — boto3 clients are not thread-safe when shared; FastAPI handles per-request.
    return get_s3_client()
