from __future__ import annotations
import json
from pathlib import Path

_PATH = Path(__file__).parent.parent / "settings.json"

DEFAULTS: dict = {
    "width": 120,
    "height_auto": True,
    "height": 40,
    "charset": "standard",
    "invert": False,
    "color": False,
    "rotate": False,
    "n_frames": 24,
    "fps": 12,
    "last_directory": "",
}


def load() -> dict:
    if _PATH.exists():
        try:
            with _PATH.open(encoding="utf-8") as f:
                saved = json.load(f)
            return {**DEFAULTS, **saved}
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULTS.copy()


def save(data: dict) -> None:
    try:
        with _PATH.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError:
        pass
