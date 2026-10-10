"""Telegram bot: allowlist, session map, single-worker queue, instant ack,
oversized-result attachments, config commands, photo albums.
See CLAUDE.md for the full contract.
"""
import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from telegram import Message, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import archive_index
import fetcher
import formatting
import render_config
import runner
import sessions
from config_store import ConfigStore, load_raw, write_config
from photos import download_photos

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "/app/config/config.json"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
SESSIONS_PATH = DATA_DIR / "sessions.json"
EVALUATIONS_DIR = DATA_DIR / "evaluations"
UPLOADS_DIR = DATA_DIR / "uploads"
COST_LOG_PATH = DATA_DIR / "cost_log.jsonl"

DEFAULT_ALLOWED_TOOLS = ["WebFetch", "WebSearch", "Read"]
DEFAULT_MAX_TURNS = 40
DEFAULT_TIMEOUT_SECONDS = 600
ALBUM_DEBOUNCE_SECONDS = 5.0
GALLERY_FETCH_TIMEOUT_SECONDS = 45.0
URL_RE = re.compile(r"https?://\S+")

HELP_TEXT = (
    "Send a listing link to get an evaluation, or ask a follow-up question to "
    "continue the conversation. Send listing photos as an album to have them "
    "analyzed too.\n\n"
    "Commands:\n"
    "/rule <text> — add a standing rule to the evaluator's config\n"
    "/config — show the current config.json\n"
    "/new — start a fresh conversation (forgets earlier context in this chat)\n"
    "/reload — force re-read config.json and report any errors\n"
    "/cost — show evaluation cost so far\n"
    "/help — show this message"
)


def check_allowed(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> Tuple[bool, dict, Optional[str]]:
    config, config_error = context.bot_data["config_store"].load()
    allowed_chat_ids = set(config.get("allowed_chat_ids", []))
    return chat_id in allowed_chat_ids, config, config_error


def archive_evaluation(job_id: str, answer: str, raw_result: dict) -> Path:
    EVALUATIONS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = EVALUATIONS_DIR / f"{job_id}.md"
    md_path.write_text(answer, encoding="utf-8")
    json_path = EVALUATIONS_DIR / f"{job_id}_raw.json"
    json_path.write_text(json.dumps(raw_result, indent=2), encoding="utf-8")
    return md_path


def log_cost(chat_id: int, message_id: int, result: dict) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "chat_id": chat_id,
        "message_id": message_id,
        "session_id": result.get("session_id"),
        "cost_usd": result.get("total_cost_usd"),
        "num_turns": result.get("num_turns"),
        "duration_ms": result.get("duration_ms"),
    }
    COST_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with COST_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.text:
        return

    allowed, config, config_error = check_allowed(context, message.chat_id)
    if not allowed:
        logger.info("ignoring message from non-allowlisted chat_id=%s", message.chat_id)
        return

    if config_error:
        await message.reply_text(f"Config error, using last good config:\n{config_error}")

    await message.reply_text("Evaluating…")
    await context.bot_data["queue"].put({"message": message, "config": config, "text": message.text})


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not message.photo:
        return

    allowed, config, config_error = check_allowed(context, message.chat_id)
    if not allowed:
        logger.info("ignoring photo from non-allowlisted chat_id=%s", message.chat_id)
        return

    if config_error:
        await message.reply_text(f"Config error, using last good config:\n{config_error}")

    media_group_id = message.media_group_id
    if media_group_id is None:
        await message.reply_text("Evaluating 1 photo…")
        await context.bot_data["queue"].put({"message": message, "config": config, "photo_messages": [message]})
        return

    key = (message.chat_id, media_group_id)
    buffers = context.bot_data["album_buffers"]
    buf = buffers.setdefault(key, {"messages": [], "task": None})
    buf["messages"].append(message)
    if buf["task"] is not None:
        buf["task"].cancel()
    buf["task"] = asyncio.create_task(_flush_album(context, key))


async def _flush_album(context: ContextTypes.DEFAULT_TYPE, key: Tuple[int, str]) -> None:
    await asyncio.sleep(ALBUM_DEBOUNCE_SECONDS)
    buffers = context.bot_data["album_buffers"]
    buf = buffers.pop(key, None)
    if not buf:
        return

    messages: List[Message] = buf["messages"]
    chat_id = key[0]
    allowed, config, _ = check_allowed(context, chat_id)
    if not allowed:
        return

    primary = messages[-1]
    await primary.reply_text(f"Evaluating {len(messages)} photos…")
    await context.bot_data["queue"].put({"message": primary, "config": config, "photo_messages": messages})


async def _fetch_gallery_note(listing_url: str, cwd: Path) -> str:
    """Best-effort: auto-fetch the listing's gallery, return a prompt
    addendum describing what was saved (or nothing if the fetch failed)."""
    try:
        filenames = await asyncio.wait_for(
            fetcher.fetch_gallery(listing_url, cwd), timeout=GALLERY_FETCH_TIMEOUT_SECONDS
        )
    except Exception:
        logger.exception("gallery auto-fetch failed for %s", listing_url)
        return ""

    if not filenames:
        return ""

    return (
        f"\n\n{len(filenames)} image(s) were auto-fetched from the listing page and saved "
        f"in the current working directory: {', '.join(filenames)}. Read them and fold the "
        "findings into Photo findings (one may be a full-page screenshot instead of "
        "individual gallery photos, if the gallery couldn't be extracted automatically)."
    )


async def process_job(job: dict) -> None:
    message: Message = job["message"]
    config = job["config"]
    chat_id = message.chat_id
    job_id = f"{chat_id}_{message.message_id}"

    runtime = config.get("runtime", {})
    allowed_tools = " ".join(runtime.get("allowed_tools", DEFAULT_ALLOWED_TOOLS))
    max_turns = runtime.get("max_turns", DEFAULT_MAX_TURNS)
    timeout_seconds = runtime.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)

    system_prompt = render_config.render(config)
    session_id = sessions.get_session_id(SESSIONS_PATH, chat_id)
    cwd = UPLOADS_DIR / job_id

    listing_url: Optional[str] = None
    photo_messages: Optional[List[Message]] = job.get("photo_messages")
    if photo_messages:
        filenames = await download_photos(photo_messages, cwd)
        caption = next((m.caption for m in photo_messages if m.caption), "")
        prompt_text = (
            (f"{caption}\n\n" if caption else "")
            + f"Read and analyze these {len(filenames)} listing photos saved in the "
            "current working directory, and fold the findings into Photo findings: "
            + ", ".join(filenames)
        )
    else:
        prompt_text = job["text"]
        listing_url_match = URL_RE.search(prompt_text)
        if listing_url_match:
            listing_url = listing_url_match.group(0).rstrip(".,;)")
            prompt_text += await _fetch_gallery_note(listing_url, cwd)

    try:
        result = await asyncio.to_thread(
            runner.run_claude,
            prompt_text,
            system_prompt,
            cwd,
            session_id=session_id,
            allowed_tools=allowed_tools,
            max_turns=max_turns,
            timeout_seconds=timeout_seconds,
        )
    except runner.RunnerTimeout as exc:
        await message.reply_text(f"Evaluation timed out: {exc}")
        return
    except runner.RunnerError as exc:
        logger.exception("runner error for job %s", job_id)
        await message.reply_text(f"Something went wrong evaluating that:\n{exc}")
        return

    sessions.set_session_id(SESSIONS_PATH, chat_id, result["session_id"])
    log_cost(chat_id, message.message_id, result)

    answer = result.get("result", "")
    archive_path = archive_evaluation(job_id, answer, result)
    archive_index.append_entry(
        EVALUATIONS_DIR / "index.jsonl",
        {
            "job_id": job_id,
            "chat_id": chat_id,
            "message_id": message.message_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": result.get("session_id"),
            "listing_url": listing_url,
            "verdict": archive_index.extract_verdict(answer),
            "cost_usd": result.get("total_cost_usd"),
            "md_path": str(archive_path.relative_to(DATA_DIR)),
        },
    )

    message_text, needs_attachment = formatting.split_for_telegram(answer)
    await message.reply_text(message_text)
    if needs_attachment:
        with archive_path.open("rb") as f:
            await message.reply_document(document=f, filename=archive_path.name)


async def worker(application: Application) -> None:
    queue: asyncio.Queue = application.bot_data["queue"]
    while True:
        job = await queue.get()
        try:
            await process_job(job)
        except Exception:
            logger.exception("job failed")
            try:
                await job["message"].reply_text("Something went wrong evaluating that; check the logs.")
            except Exception:
                logger.exception("could not report failure back to chat")
        finally:
            queue.task_done()


async def cmd_rule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    allowed, _, _ = check_allowed(context, message.chat_id)
    if not allowed:
        return

    rule_text = " ".join(context.args).strip()
    if not rule_text:
        await message.reply_text("Usage: /rule <text>")
        return

    try:
        config = load_raw(CONFIG_PATH)
    except (OSError, json.JSONDecodeError) as exc:
        await message.reply_text(f"Can't add a rule right now, {CONFIG_PATH} is invalid:\n{exc}")
        return

    config.setdefault("process_rules", []).append(rule_text)
    write_config(CONFIG_PATH, config)
    await message.reply_text(f"Added rule:\n{rule_text}")


async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    allowed, _, _ = check_allowed(context, message.chat_id)
    if not allowed:
        return

    with CONFIG_PATH.open("rb") as f:
        await message.reply_document(document=f, filename=CONFIG_PATH.name, caption="Current config.json")


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    allowed, _, _ = check_allowed(context, message.chat_id)
    if not allowed:
        return

    sessions.clear_session_id(SESSIONS_PATH, message.chat_id)
    await message.reply_text("Started a new conversation — the next message won't use earlier context.")


async def cmd_reload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    allowed, config, config_error = check_allowed(context, message.chat_id)
    if not allowed:
        return

    if config_error:
        await message.reply_text(f"Reload failed, keeping last good config:\n{config_error}")
        return

    await message.reply_text(
        "Config reloaded OK: "
        f"{len(config.get('process_rules', []))} process rule(s), "
        f"{len(config.get('must_haves', []))} must-have(s), "
        f"{len(config.get('allowed_chat_ids', []))} allowed chat(s)."
    )


async def cmd_cost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    allowed, _, _ = check_allowed(context, message.chat_id)
    if not allowed:
        return

    chat_id = message.chat_id
    total = chat_total = 0.0
    count = chat_count = 0
    if COST_LOG_PATH.exists():
        with COST_LOG_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cost = entry.get("cost_usd") or 0.0
                total += cost
                count += 1
                if entry.get("chat_id") == chat_id:
                    chat_total += cost
                    chat_count += 1

    await message.reply_text(
        f"This chat: ${chat_total:.2f} across {chat_count} evaluation(s)\n"
        f"All chats: ${total:.2f} across {count} evaluation(s)"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    allowed, _, _ = check_allowed(context, message.chat_id)
    if not allowed:
        return
    await message.reply_text(HELP_TEXT)


async def post_init(application: Application) -> None:
    application.bot_data["worker_task"] = asyncio.create_task(worker(application))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    application = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .build()
    )
    application.bot_data["config_store"] = ConfigStore(CONFIG_PATH)
    application.bot_data["queue"] = asyncio.Queue()
    application.bot_data["album_buffers"] = {}

    application.add_handler(CommandHandler("rule", cmd_rule))
    application.add_handler(CommandHandler("config", cmd_config))
    application.add_handler(CommandHandler("new", cmd_new))
    application.add_handler(CommandHandler("reload", cmd_reload))
    application.add_handler(CommandHandler("cost", cmd_cost))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
