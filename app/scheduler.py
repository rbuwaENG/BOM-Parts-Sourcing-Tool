from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

META_PATH = Path("data/metadata.json")
PROGRESS_PATH = Path("data/progress.json")


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


def write_progress(name: str, data: Dict[str, Any]) -> None:
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    all_data: Dict[str, Any] = {}
    if PROGRESS_PATH.exists():
        try:
            all_data = json.loads(PROGRESS_PATH.read_text())
        except Exception:
            all_data = {}
    all_data[name] = data
    PROGRESS_PATH.write_text(json.dumps(all_data, indent=2))


def read_progress(name: str) -> Dict[str, Any]:
    if not PROGRESS_PATH.exists():
        return {}
    try:
        all_data = json.loads(PROGRESS_PATH.read_text())
        return all_data.get(name, {})
    except Exception:
        return {}