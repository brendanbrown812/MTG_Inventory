from __future__ import annotations

import os
import logging
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


_test_dir = tempfile.TemporaryDirectory(prefix="spellbinder-tests-")
_db_path = Path(_test_dir.name) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path.as_posix()}"
os.environ["SPELLBINDER_LOG_DIR"] = str(Path(_test_dir.name) / "logs")
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
os.environ.pop("APP_API_KEY", None)
os.environ.pop("REQUIRE_AUTH", None)
os.environ.pop("EXTERNAL_AUTH_ENABLED", None)

from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import (  # noqa: E402
    _enrichment_jobs,
    _manabox_import_progress,
    _text_import_progress,
    app,
)


@pytest.fixture(autouse=True)
def clean_database() -> Iterator[None]:
    with SessionLocal() as db:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
    _enrichment_jobs.clear()
    _manabox_import_progress.clear()
    _text_import_progress.clear()
    settings.app_api_key = ""
    yield


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_database() -> Iterator[None]:
    yield
    engine.dispose()
    logger = logging.getLogger("spellbinder")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    _test_dir.cleanup()
