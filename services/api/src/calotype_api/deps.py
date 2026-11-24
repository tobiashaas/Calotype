from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache

from fastapi import Depends
from sqlalchemy.orm import Session

from calotype_api.storage import blob_store
from calotype_io import BlobStore
from calotype_persistence.session import get_session_factory, session_scope
from calotype_persistence.stores import SqlStore, Store
from calotype_queue.publisher import RedisQueuePublisher, redis_from_env


@lru_cache(maxsize=1)
def session_factory_holder():
    return get_session_factory()


def get_session() -> Generator[Session, None, None]:
    factory = session_factory_holder()
    with session_scope(factory) as session:
        yield session


def get_store(session: Session = Depends(get_session)) -> Store:
    """The routes' data access: Postgres in one session per request (committed when the route
    returns). Tests override it with `calotype_persistence.memory.MemoryStore`."""
    return SqlStore(session)


def get_publisher() -> RedisQueuePublisher:
    # Not cached intentionally to respect env mocks in tests; cheap construction.
    return RedisQueuePublisher(redis_from_env())


def get_storage() -> BlobStore:
    """Previews go to the blob store (S3 from the environment). Tests override it with
    `calotype_io.MemoryBlobStore`."""
    return blob_store()
