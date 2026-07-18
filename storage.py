"""
Lightweight JSON-backed per-guild storage.

Not a real database — fine for a single-instance bot on Railway/Wispbyte with
a persistent volume. If you outgrow this (thousands of guilds, high write
volume), swap it for SQLite/Postgres, but the interface below can stay the
same so the cogs don't need to change.
"""

from __future__ import annotations

import json
import os
import asyncio
from pathlib import Path
from typing import Any

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

_lock = asyncio.Lock()
_cache: dict[str, dict[str, Any]] = {}


def _path(name: str) -> Path:
    return DATA_DIR / f"{name}.json"


def _load(name: str) -> dict[str, Any]:
    if name in _cache:
        return _cache[name]
    p = _path(name)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                _cache[name] = json.load(f)
        except (json.JSONDecodeError, OSError):
            _cache[name] = {}
    else:
        _cache[name] = {}
    return _cache[name]


async def _save(name: str) -> None:
    async with _lock:
        p = _path(name)
        tmp = p.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_cache.get(name, {}), f, indent=2)
        tmp.replace(p)


class Store:
    """A single JSON "table" (e.g. 'guild_config', 'warnings')."""

    def __init__(self, name: str):
        self.name = name

    def get(self, guild_id: int, default: Any = None) -> Any:
        data = _load(self.name)
        return data.get(str(guild_id), default)

    async def set(self, guild_id: int, value: Any) -> None:
        data = _load(self.name)
        data[str(guild_id)] = value
        await _save(self.name)

    async def update(self, guild_id: int, **kwargs) -> dict:
        data = _load(self.name)
        entry = data.setdefault(str(guild_id), {})
        entry.update(kwargs)
        await _save(self.name)
        return entry

    def all(self) -> dict:
        return _load(self.name)


guild_config = Store("guild_config")   # prefixes, mod-log channel, toggles
warnings_db = Store("warnings")        # moderation warning history
antinuke_db = Store("antinuke")        # antinuke config + whitelist
