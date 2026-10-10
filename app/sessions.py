"""Per-chat Claude session_id map, persisted at /data/sessions.json.

One Telegram chat maps to one Claude Code session_id so a follow-up question
resumes the same conversation (see the runner contract in CLAUDE.md).
"""
import json
import logging
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("could not read session map at %s: %s", path, exc)
        return {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    tmp.replace(path)


def get_session_id(path: Path, chat_id: int) -> Optional[str]:
    with _lock:
        return _load(path).get(str(chat_id))


def set_session_id(path: Path, chat_id: int, session_id: str) -> None:
    with _lock:
        data = _load(path)
        data[str(chat_id)] = session_id
        _save(path, data)


def clear_session_id(path: Path, chat_id: int) -> None:
    with _lock:
        data = _load(path)
        if data.pop(str(chat_id), None) is not None:
            _save(path, data)
