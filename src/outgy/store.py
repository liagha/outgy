import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


class Store:
    def __init__(self, path: Path):
        self._path = path
        if path.exists():
            self._data = json.loads(path.read_text(encoding="utf-8"))
        else:
            self._data = {}
        self._data.setdefault("users", {})
        self._data.setdefault("announced", {})
        if not self._data.get("key"):
            self._data["key"] = Fernet.generate_key().decode()
            self._save()
        self._fernet = Fernet(self._data["key"].encode())

    def _save(self) -> None:
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self._path)

    def set_bill(self, chat_id: int, bill_id: str) -> None:
        key = str(chat_id)
        encrypted = self._fernet.encrypt(bill_id.encode()).decode()
        entry = self._data["users"].get(key, {})
        entry["bill"] = encrypted
        entry.setdefault("added_at", int(time.time()))
        self._data["users"][key] = entry
        self._data["announced"].setdefault(key, {})
        self._save()

    def set_token(self, chat_id: int, token: str) -> None:
        key = str(chat_id)
        entry = self._data["users"].get(key, {})
        entry["token"] = self._fernet.encrypt(token.encode()).decode()
        entry["token_at"] = int(time.time())
        self._data["users"][key] = entry
        self._save()

    def _decrypt_field(self, chat_id: int, field: str) -> str | None:
        entry = self._data["users"].get(str(chat_id))
        if not entry or not entry.get(field):
            return None
        try:
            return self._fernet.decrypt(entry[field].encode()).decode()
        except Exception:
            logger.exception("failed to decrypt %s for chat %s", field, chat_id)
            return None

    def get_bill(self, chat_id: int) -> str | None:
        return self._decrypt_field(chat_id, "bill")

    def get_token(self, chat_id: int) -> str | None:
        return self._decrypt_field(chat_id, "token")

    def clear_token(self, chat_id: int) -> None:
        entry = self._data["users"].get(str(chat_id))
        if entry:
            entry.pop("token", None)
            entry.pop("token_at", None)
            self._save()

    def remove_user(self, chat_id: int) -> bool:
        key = str(chat_id)
        existed = key in self._data["users"]
        self._data["users"].pop(key, None)
        self._data["announced"].pop(key, None)
        if existed:
            self._save()
        return existed

    def user_ids(self) -> list[int]:
        return [int(k) for k in self._data["users"]]

    def announced_keys(self, chat_id: int) -> set[str]:
        return set(self._data["announced"].get(str(chat_id), {}))

    def mark_announced(self, chat_id: int, keys: list[str]) -> None:
        key = str(chat_id)
        announced = self._data["announced"].setdefault(key, {})
        now = datetime.now(timezone.utc).timestamp()
        for k in keys:
            announced[k] = now
        cutoff = now - 7 * 86400
        self._data["announced"][key] = {
            k: ts for k, ts in announced.items() if ts >= cutoff
        }
        self._save()
