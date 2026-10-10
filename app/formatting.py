"""Splits a full evaluation into a chat-sized message plus a full-text attachment."""

TELEGRAM_MESSAGE_LIMIT = 4096
_SAFETY_MARGIN = 200  # room for the "full evaluation attached" footer


def extract_short_verdict(markdown: str, limit: int) -> str:
    lines = markdown.splitlines()
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") and "verdict" in stripped.lower():
            start = i
            break

    if start is not None:
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if lines[j].strip().startswith("#"):
                end = j
                break
        section = "\n".join(lines[start:end]).strip()
    else:
        section = markdown.strip()

    if len(section) > limit:
        section = section[: limit - 1].rstrip() + "…"
    return section


def split_for_telegram(markdown: str) -> tuple[str, bool]:
    """Returns (message_text, needs_attachment)."""
    if len(markdown) <= TELEGRAM_MESSAGE_LIMIT:
        return markdown, False

    short = extract_short_verdict(markdown, TELEGRAM_MESSAGE_LIMIT - _SAFETY_MARGIN)
    message = f"{short}\n\n(Full evaluation attached as a file.)"
    return message, True
