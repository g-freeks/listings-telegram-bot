"""Wraps the `claude -p` runner contract from CLAUDE.md as a subprocess call."""
import json
import subprocess
from pathlib import Path
from typing import Optional

CLAUDE_SETTINGS_PATH = Path(__file__).parent / "claude_settings.json"


class RunnerError(Exception):
    pass


class RunnerTimeout(RunnerError):
    pass


def run_claude(
    message: str,
    system_prompt: str,
    cwd: Path,
    *,
    session_id: Optional[str],
    allowed_tools: str,
    max_turns: int,
    timeout_seconds: int,
) -> dict:
    """Runs `claude -p` once and returns the parsed --output-format json result."""
    cmd = [
        "claude", "-p", message,
        "--output-format", "json",
        "--append-system-prompt", system_prompt,
        "--allowedTools", allowed_tools,
        "--max-turns", str(max_turns),
        "--settings", str(CLAUDE_SETTINGS_PATH),
        "--permission-prompts", "none",
    ]
    if session_id:
        cmd += ["--resume", session_id]

    cwd.mkdir(parents=True, exist_ok=True)

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RunnerTimeout(f"claude -p timed out after {timeout_seconds}s") from exc

    if proc.returncode != 0:
        raise RunnerError(f"claude -p exited {proc.returncode}: {proc.stderr[-2000:]}")

    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RunnerError(f"could not parse claude -p output: {exc}") from exc

    if result.get("is_error"):
        raise RunnerError(f"claude -p reported an error: {result.get('result')}")

    return result
