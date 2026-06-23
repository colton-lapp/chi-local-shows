import pytest
import db as db_module


@pytest.fixture(autouse=False)
def tmp_db(monkeypatch, tmp_path):
    """Redirect db.DB_PATH to a temp file and initialize schema."""
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")
    db_module.init_db()
