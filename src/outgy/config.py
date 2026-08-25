import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    saapa_token: str
    saapa_base_url: str
    poll_interval: int
    db_path: Path
    announce_days: int

    @classmethod
    def load(cls, *, bot_token_required: bool = True) -> "Settings":
        load_dotenv()
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if bot_token_required and not bot_token:
            raise SystemExit("TELEGRAM_BOT_TOKEN is missing (put it in .env)")
        return cls(
            bot_token=bot_token,
            saapa_token=os.environ.get("SAAPA_TOKEN", "").strip(),
            saapa_base_url=os.environ.get("SAAPA_API_BASE", "https://uiapi.saapa.ir").rstrip("/"),
            poll_interval=int(os.environ.get("POLL_INTERVAL", "900")),
            db_path=Path(os.environ.get("OUTGY_DB", "outgy.json")),
            announce_days=int(os.environ.get("ANNOUNCE_DAYS", "3")),
        )
