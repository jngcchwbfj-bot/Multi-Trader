"""Writes simple, human-readable JSON memory records under data/memory/.

This is intentionally minimal: one JSON file per session/backtest run,
capturing enough to review "what happened" later. It is not a database or
a learning system - just an audit-friendly record store.
"""

import json
from pathlib import Path
from typing import Any

DEFAULT_MEMORY_DIR = Path("data/memory")


def _json_default(obj: Any) -> Any:
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


class MemoryStore:
    """Writes JSON memory records for sessions and backtests."""

    def __init__(self, memory_dir: Path | str = DEFAULT_MEMORY_DIR) -> None:
        self.memory_dir = Path(memory_dir)

    def write_session_record(self, session_id: str, record: dict) -> Path:
        out_dir = self.memory_dir / "sessions"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{session_id}.json"
        path.write_text(json.dumps(record, indent=2, default=_json_default))
        return path

    def write_backtest_record(self, backtest_id: str, record: dict) -> Path:
        out_dir = self.memory_dir / "backtests"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{backtest_id}.json"
        path.write_text(json.dumps(record, indent=2, default=_json_default))
        return path
