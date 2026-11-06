import pytest
from fastapi.testclient import TestClient

from rowlab.app import create_app


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """Every test gets its own empty data dir instead of `~/.rowlab`."""
    path = tmp_path / "data"
    monkeypatch.setenv("ROWLAB_DATA_DIR", str(path))
    return path


@pytest.fixture
def client():
    return TestClient(create_app())
