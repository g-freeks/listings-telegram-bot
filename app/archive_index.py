"""Maintains an index of archived evaluations (data/evaluations/index.jsonl)
so Phase 5 (compare/re-rank archived listings) has something to read."""
import json
import re
from pathlib import Path
from typing import Optional

_VERDICT_RE = re.compile(r"Pursue with caveats|Pursue|Pass")


def extract_verdict(markdown: str) -> Optional[str]:
    """Looks for a 'Pursue' / 'Pursue with caveats' / 'Pass' label near a
    heading that mentions "verdict"; falls back to a whole-document search."""
    lines = markdown.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") and "verdict" in stripped.lower():
            window = "\n".join(lines[i : i + 3])
            match = _VERDICT_RE.search(window)
            if match:
                return match.group(0)
    match = _VERDICT_RE.search(markdown)
    return match.group(0) if match else None


def append_entry(index_path: Path, entry: dict) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
