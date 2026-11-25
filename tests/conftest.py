import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MASTERMAIL_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("MASTERMAIL_WORKSPACE", str(tmp_path / "ws"))
    from mastermail import paths
    paths.set_data_dir(None)
    import mastermail.settings as settings_mod
    monkeypatch.setattr(settings_mod, "keyring", None)
    yield tmp_path
    paths.set_data_dir(None)
