"""Filesystem locations that behave the same from source and from a frozen exe."""
from __future__ import annotations

import os
import sys
from pathlib import Path

DATA_FOLDER_NAME = "MasterMail-data"


def bundle_dir() -> Path:
    """Folder holding bundled read-only resources (web UI, assets)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    return Path(__file__).resolve().parent.parent


def resource(*parts: str) -> Path:
    return bundle_dir().joinpath(*parts)


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:  # noqa: BLE001
        return False


_DATA_DIR: Path | None = None


def data_dir() -> Path:
    """Settings, database, uploads and the Chrome profile.

    Portable exe keeps everything next to itself; when that folder is read-only
    we fall back to the user profile. ``MASTERMAIL_DATA`` overrides both (tests).
    """
    global _DATA_DIR
    if _DATA_DIR is not None:
        return _DATA_DIR
    override = os.environ.get("MASTERMAIL_DATA")
    if override:
        path = Path(override)
        path.mkdir(parents=True, exist_ok=True)
        _DATA_DIR = path
        return path
    if getattr(sys, "frozen", False):
        portable = app_dir() / DATA_FOLDER_NAME
        if _writable(portable):
            _DATA_DIR = portable
            return portable
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    path = Path(base) / "MasterMail" if base else Path.home() / ".mastermail"
    path.mkdir(parents=True, exist_ok=True)
    _DATA_DIR = path
    return path


def set_data_dir(path: str | Path | None) -> None:
    global _DATA_DIR
    _DATA_DIR = Path(path) if path else None


def default_workspace() -> Path:
    override = os.environ.get("MASTERMAIL_WORKSPACE")
    if override:
        return Path(override)
    docs = Path.home() / "Documents"
    if docs.is_dir():
        return docs / "MasterMail"
    return data_dir() / "workspace"


def uploads_dir() -> Path:
    path = data_dir() / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_file() -> Path:
    return data_dir() / "settings.json"


def database_file() -> Path:
    return data_dir() / "mastermail.db"


def chrome_profile_dir() -> Path:
    return data_dir() / "chrome-profile"


def log_file() -> Path:
    return data_dir() / "mastermail.log"
