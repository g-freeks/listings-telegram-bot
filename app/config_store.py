"""Loads config.json on every message, keeping the last good version on
parse/validation errors, plus raw load/write helpers for commands (/rule)
that edit the file directly.

Per CLAUDE.md: "Invalid config.json: keep last good version, report the parse
error in chat." and "config.json (bot writes it for /rule; Claude must not)."
"""
import json
import logging
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

REQUIRED_LIST_FIELDS = [
    "base_prompt",
    "needs",
    "no_gos",
    "must_haves",
    "nice_to_haves",
    "commute_destinations",
    "process_rules",
    "allowed_chat_ids",
]


def validate_config(config: dict) -> List[str]:
    """Returns a list of human-readable errors; empty means the config is usable."""
    errors = []
    if not isinstance(config, dict):
        return ["config must be a JSON object"]

    for field in REQUIRED_LIST_FIELDS:
        if field not in config:
            errors.append(f"missing required field: {field}")
        elif not isinstance(config[field], list):
            errors.append(f"{field} must be a list")

    if "buyer_profile" not in config:
        errors.append("missing required field: buyer_profile")
    elif not isinstance(config["buyer_profile"], dict):
        errors.append("buyer_profile must be an object")

    runtime = config.get("runtime")
    if not isinstance(runtime, dict):
        errors.append("missing or invalid runtime object")
    else:
        if not isinstance(runtime.get("allowed_tools"), list):
            errors.append("runtime.allowed_tools must be a list")
        if not isinstance(runtime.get("max_turns"), int):
            errors.append("runtime.max_turns must be an int")
        if not isinstance(runtime.get("timeout_seconds"), int):
            errors.append("runtime.timeout_seconds must be an int")

    return errors


def load_raw(path: Path) -> dict:
    """Reads config.json without caching or validation; raises on bad JSON."""
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_config(path: Path, config: dict) -> None:
    """Atomically writes config.json. Only command handlers (e.g. /rule) call
    this — the evaluating Claude subprocess must never write config.json."""
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(path)


class ConfigStore:
    def __init__(self, path: Path):
        self._path = path
        self._last_good: Optional[dict] = None

    def load(self) -> Tuple[dict, Optional[str]]:
        """Returns (config, error). `error` is None on success. On a parse or
        validation error, returns the last good config (or {} if there isn't
        one yet) alongside a human-readable error message to report in chat."""
        try:
            config = load_raw(self._path)
        except (OSError, json.JSONDecodeError) as exc:
            error = f"{self._path} is invalid: {exc}"
            if self._last_good is None:
                logger.error(error)
                return {}, error
            logger.warning("%s — keeping last good config", error)
            return self._last_good, error

        errors = validate_config(config)
        if errors:
            error = f"{self._path} failed validation: " + "; ".join(errors)
            if self._last_good is None:
                logger.error(error)
                return {}, error
            logger.warning("%s — keeping last good config", error)
            return self._last_good, error

        self._last_good = config
        return config, None
