"""User settings (JSON) and secrets (OS keyring)."""
from __future__ import annotations

import copy
import getpass
import json
import threading
from typing import Any

from .paths import default_workspace, settings_file

try:  # keyring talks to Windows Credential Manager / macOS Keychain / Secret Service
    import keyring  # type: ignore
except Exception:  # noqa: BLE001
    keyring = None

KEYRING_SERVICE = "MasterMail"
SECRET_KINDS = ("smtp_password", "anthropic_api_key")

DEFAULT_BASE_URL = (
    "https://admin.digikala.com/marketplace/sellers/item/{id}/"
    "?_back=https://admin.digikala.com/marketplace/sellers/"
)

DEFAULTS: dict[str, Any] = {
    "onboarded": False,
    "workspace_dir": "",
    "smtp": {
        "host": "mail.digikala.com",
        "port": 587,
        "security": "starttls",       # starttls | ssl | none
        "username": "",
        "use_system_username": True,
        "from_email": "",
        "from_name": "",
        "reply_to": "",
        "remember_password": True,
        "timeout": 60,
    },
    "sending": {
        "delay": 1.5,                 # seconds between messages
        "pause_every": 50,            # take a breath every N messages
        "pause_seconds": 20,
        "bcc_self": False,
        "html": True,
        "signature": "",
    },
    "crawler": {
        "base_url": DEFAULT_BASE_URL,
        "email_selector": 'input[name="email"]',
        "name_selector": 'input[name="business_name_fa"]',
        "delay": 1.0,
        "page_timeout": 30,
        "element_timeout": 10,
        "retries": 2,
        "headless": False,
        "keep_profile": True,
        "chrome_binary": "",
        "chromedriver_path": "",
        "login_wait": 300,
        "cache_days": 30,
    },
    "ai": {
        "enabled": True,
        "model": "claude-opus-5-5",
    },
    "appearance": {
        "theme": "system",           # system | light | dark
        "accent": "blue",
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _merge(out[key], value)
        elif key in out:
            expected = type(out[key])
            try:
                if expected is bool:
                    value = bool(value)
                elif expected is int and not isinstance(value, bool):
                    value = int(float(value))
                elif expected is float:
                    value = float(value)
                elif expected is str:
                    value = "" if value is None else str(value)
            except (TypeError, ValueError):
                continue
            out[key] = value
    return out


class Settings:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data = copy.deepcopy(DEFAULTS)
        self._memory_secrets: dict[str, str] = {}
        self.load()

    def load(self) -> None:
        path = settings_file()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._data = _merge(DEFAULTS, raw)
        except FileNotFoundError:
            pass
        except Exception:  # noqa: BLE001 - a broken file must not stop the app
            pass

    def save(self) -> None:
        path = settings_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with self._lock:
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def get(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def section(self, name: str) -> dict:
        with self._lock:
            return copy.deepcopy(self._data.get(name, {}))

    def update(self, patch: dict) -> dict:
        with self._lock:
            self._data = _merge(self._data, patch)
            self.save()
            return self.get()

    # -- derived -----------------------------------------------------------
    def workspace(self):
        from pathlib import Path

        custom = self._data.get("workspace_dir")
        path = Path(custom) if custom else default_workspace()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def smtp_username(self) -> str:
        smtp = self._data["smtp"]
        user = smtp.get("username", "").strip()
        if not user and smtp.get("use_system_username"):
            try:
                user = getpass.getuser()
            except Exception:  # noqa: BLE001
                user = ""
        return user

    def from_address(self) -> str:
        smtp = self._data["smtp"]
        if smtp.get("from_email"):
            return smtp["from_email"].strip()
        user = self.smtp_username()
        if "@" in user:
            return user
        if "\\" in user:  # DOMAIN\user
            user = user.split("\\", 1)[1]
        host = smtp.get("host", "")
        domain = host.split(".", 1)[1] if host.count(".") >= 2 else host
        return f"{user}@{domain}" if user and domain else user

    # -- secrets -----------------------------------------------------------
    def keyring_available(self) -> bool:
        if keyring is None:
            return False
        try:
            backend = keyring.get_keyring()
            return "fail" not in type(backend).__module__.lower()
        except Exception:  # noqa: BLE001
            return False

    def _account(self, kind: str) -> str:
        if kind == "smtp_password":
            return f"smtp:{self.smtp_username()}"
        return kind

    def get_secret(self, kind: str) -> str:
        if kind in self._memory_secrets:
            return self._memory_secrets[kind]
        if self.keyring_available():
            try:
                return keyring.get_password(KEYRING_SERVICE, self._account(kind)) or ""
            except Exception:  # noqa: BLE001
                return ""
        return ""

    def set_secret(self, kind: str, value: str, persist: bool = True) -> bool:
        """Store a secret; returns True when it reached the OS keyring."""
        if kind not in SECRET_KINDS:
            raise ValueError(kind)
        value = value or ""
        self._memory_secrets[kind] = value
        if not persist or not self.keyring_available():
            return False
        try:
            if value:
                keyring.set_password(KEYRING_SERVICE, self._account(kind), value)
            else:
                try:
                    keyring.delete_password(KEYRING_SERVICE, self._account(kind))
                except Exception:  # noqa: BLE001
                    pass
            return True
        except Exception:  # noqa: BLE001
            return False

    def public(self) -> dict:
        data = self.get()
        data["derived"] = {
            "smtp_username": self.smtp_username(),
            "from_address": self.from_address(),
            "workspace": str(self.workspace()),
            "keyring": self.keyring_available(),
            "has_smtp_password": bool(self.get_secret("smtp_password")),
            "has_ai_key": bool(self.get_secret("anthropic_api_key")),
        }
        return data
