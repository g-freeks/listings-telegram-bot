# House-Listing Bot

Private experimental project: a Telegram bot that qualifies Swedish house listings
(cost / value / risk) for a buyer couple. It wraps the Claude Code CLI
(`claude -p`) inside a Docker container on a home server (x86).

Full plan (architecture, components, security, phases):
https://claude.ai/code/artifact/5b90a736-6a7a-4898-8ba5-71b27e3a0e53

## Decisions already made

- Language: Python service wrapping `claude -p` as a subprocess (Agent SDK is a later option).
- Telegram: `python-telegram-bot`, long polling, ONE shared group chat (two users + bot).
  Privacy mode must be turned off in BotFather (`/setprivacy`) so the bot sees links and photos.
- Auth: subscription token for now (`claude setup-token` -> `CLAUDE_CODE_OAUTH_TOKEN` in `.env`).
  Switch to `ANTHROPIC_API_KEY` if the monthly Agent SDK credit runs short.
- Server: x86, RAM is not a constraint (headless Chromium OK).
- Base prompt, buyer profile and checklists live in `./config.json` (repo root, gitignored —
  holds real personal data), mounted into the container, re-read on EVERY message and passed
  via `--append-system-prompt`. `config/config.json` is a tracked, anonymized example of the
  same schema, for the public repo — not live-mounted.

## Runner contract

```bash
claude -p "$MESSAGE" --output-format json [--resume "$SESSION_ID"] \
  --append-system-prompt "$RENDERED_CONFIG" \
  --allowedTools "WebFetch WebSearch Read" --max-turns 40
```

- First message in a chat omits `--resume`; store the returned `session_id` per chat in `/data/sessions.json`.
- Hard timeout from `runtime.timeout_seconds`; reply "Evaluating..." immediately, post result when done.
- Results > 4,096 chars: short verdict as message + full evaluation as Markdown attachment.
- Invalid config.json: keep last good version, report the parse error in chat.

## Volumes

| Host | Container | Purpose |
|---|---|---|
| `./config.json` | `/app/config/config.json` | your real config — gitignored; bot writes it for `/rule`, Claude must not (see `config/config.json` for the tracked, anonymized example) |
| `./data` | `/data` | sessions map, uploads per job, evaluation archive |
| `./claude-home` | `/home/node` (whole $HOME) | Claude Code session transcripts under `.claude/` (needed for `--resume`), plus top-level state (`~/.claude.json`) that Claude Code writes outside that subdirectory — both need to persist and be writable under `read_only: true` |
| `.env` | env vars | `TELEGRAM_BOT_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN` |

First-time setup: `cp config/config.json config.json` and fill in real buyer
details before running. No host-side `chown` setup needed: `docker-entrypoint.sh`
starts as root, runs `chown -R node:node /data /app/config /home/node`, then
drops to the `node` user via `gosu` before running anything that touches
network input (Telegram, listing pages, photos) — so `./claude-home`, `./data`
and `./config.json` can belong to whatever uid created them (e.g. right after
a fresh `git clone` on a new machine) and still work. This needs `cap_add: [CHOWN, DAC_OVERRIDE, SETUID,
SETGID]` alongside `cap_drop: ALL` (see Security rules) — `DAC_OVERRIDE` is
needed because a recursive chown must *traverse* directories it doesn't yet
own, not just a plain `CAP_CHOWN`. A plain tmpfs mount for `/home/node` was
tried first instead of the `./claude-home` bind mount, but Docker's generic
tmpfs default (mode 0755, root-owned) isn't writable by a non-root user, and
the compose `tmpfs.mode:` field gets reformatted as octal rather than used as
literal mode bits, making `1777` hard to express correctly — the bind mount
plus entrypoint chown sidesteps that entirely.

## Security rules (do not relax without asking)

- Allowlist chat IDs (`allowed_chat_ids`); ignore and log everything else.
- No Bash/Write/Edit tools for the evaluating Claude; working dir = `/data/uploads/<job>`.
- Deny reads of `/app/config` and `/proc` via Claude Code permission settings —
  **the pattern needs a double leading slash** (`Read(//app/config/**)`), not a
  single one (`Read(/app/config/**)`), to anchor to the filesystem root. The
  single-slash form silently fails to match (verified by testing: Claude could
  still read `/app/config/config.json` with it in place) — if this is ever
  touched again, verify it with a real adversarial prompt, not just by reading
  the settings file.
- Non-root (`node` user), read-only root FS, cap_drop ALL (plus the narrow
  `cap_add` above, needed only for `docker-entrypoint.sh`'s root-to-node
  handoff — the long-running bot/claude/Chromium process itself ends up with
  zero effective capabilities, confirmed via `/proc/1/status`), memory/CPU limits.
- Pin the Claude Code version in the Dockerfile.

## Phases and gates

1. Spike: Dockerfile + compose + render config + run `claude -p` by hand.
   Gate: a real listing evaluation reproduced from the CLI, cost logged.
   Test listing: any real maklarhuset.se listing URL.
2. Telegram MVP: allowlist, session map, queue, instant reply, file attachments.
   Gate: link in, verdict out; a follow-up question keeps context.
3. Config and photos: hot reload + validation, `/rule` `/config` `/new` `/reload` `/cost` `/help`,
   album collection (~5 s debounce). Gate: config edit applies to next link; 10-photo album analyzed.
4. Fetcher and hardening: Playwright gallery download (per-site selectors, screenshot fallback),
   security rules above, archive index. Gate: photos auto-fetched from a Mäklarhuset link.
5. Optional: commute times via Trafiklab ResRobot API; compare/re-rank archived listings.

Current status: Phases 1-4 done (gates passed by hand against the real Telegram
group and a real test listing, including a fully containerized run with
`docker compose` — read-only rootfs, cap_drop ALL, non-root, resource limits,
`CLAUDE_CODE_OAUTH_TOKEN` auth, and the Playwright gallery fetch all verified
together). Phase 5 (optional) not started.
