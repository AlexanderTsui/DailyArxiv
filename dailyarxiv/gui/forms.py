from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import Settings, load_settings


def load_settings_or_default(config_path: str) -> Settings:
    p = Path(config_path)
    if p.exists():
        return load_settings(p)
    return Settings()


def settings_to_ui_dict(settings: Settings) -> dict[str, Any]:
    return settings.model_dump()


def ui_dict_to_settings(ui: dict[str, Any]) -> Settings:
    return Settings.model_validate(ui)

