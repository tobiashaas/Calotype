"""Shared fixtures for the API tests.

The routes get their data access through `get_store`; here it is a `MemoryStore` (real ORM
records in dicts), so the tests run without Postgres. Redis and S3 are fakes at their own
dependencies (`get_publisher`, `get_storage`). Nothing is patched by import path: renaming an
import in `main.py` cannot break a test.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from calotype_api.deps import get_publisher, get_storage, get_store
from calotype_api.main import app
from calotype_persistence.memory import MemoryStore


@pytest.fixture()
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture()
def mock_publisher():
    pub = MagicMock()
    pub.enqueue = MagicMock()
    return pub


@pytest.fixture()
def mock_storage():
    s3 = MagicMock()
    s3.put_object = MagicMock()
    return s3


@pytest.fixture()
def client(store, mock_publisher, mock_storage) -> Generator[TestClient, None, None]:
    """TestClient whose store, queue and object storage are in memory."""
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_publisher] = lambda: mock_publisher
    app.dependency_overrides[get_storage] = lambda: mock_storage
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()
