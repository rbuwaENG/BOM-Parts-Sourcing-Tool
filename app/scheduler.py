from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

META_PATH = Path("data/metadata.json")


def set_last_update_time(dt: datetime) -> None:
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {"last_update": dt.isoformat()}
    META_PATH.write_text(json.dumps(data, indent=2))


def get_last_update_time() -> str:
    if not META_PATH.exists():
        return ""
    try:
        data = json.loads(META_PATH.read_text())
        return data.get("last_update", "")
    except Exception:
        return ""


def trigger_background_refresh() -> None:
    # Placeholder: In a real deployment, trigger APScheduler or an async task.
    set_last_update_time(datetime.utcnow())