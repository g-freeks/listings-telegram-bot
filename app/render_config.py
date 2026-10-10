#!/usr/bin/env python3
"""Render config/config.json into the text passed to `claude -p --append-system-prompt`.

Re-read on every message per the runner contract in CLAUDE.md — this module has
no caching of its own; the caller decides when to re-read and how to fall back
to the last good config on a parse error.
"""
import json
import sys


def render(config: dict) -> str:
    lines = list(config.get("base_prompt", []))

    profile = config.get("buyer_profile", {})
    if profile:
        lines.append("")
        lines.append("# Buyer profile")
        for key, value in profile.items():
            lines.append(f"- {key}: {value}")

    def section(title: str, key: str) -> None:
        items = config.get(key, [])
        if not items:
            return
        lines.append("")
        lines.append(f"# {title}")
        for item in items:
            lines.append(f"- {item}")

    section("Needs", "needs")
    section("No-gos (hard gates)", "no_gos")
    section("Must-haves", "must_haves")
    section("Nice-to-haves", "nice_to_haves")
    section("Commute destinations", "commute_destinations")
    section("Process rules", "process_rules")

    return "\n".join(lines)


def load(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "config/config.json"
    try:
        config = load(path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: invalid config at {path}: {exc}", file=sys.stderr)
        return 1
    print(render(config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
