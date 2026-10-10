# House-Listing Bot

A Telegram bot that qualifies house listings (cost / value / risk) for a buyer,
by wrapping the [Claude Code CLI](https://claude.com/claude-code) (`claude -p`)
inside a hardened Docker container. Send it a listing link in a Telegram group
and it replies with a structured evaluation; ask a follow-up question and it
keeps the conversation's context.

See [CLAUDE.md](CLAUDE.md) for the full design: architecture decisions, the
exact `claude -p` runner contract, security hardening, and the phase-by-phase
build log.

## Prerequisites

- Docker and the `docker compose` plugin
- A [Claude subscription](https://claude.com/product/claude-code) (for
  `claude setup-token`), or an Anthropic API key
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A Telegram group for the bot to operate in

## Setup

### 1. Clone and configure secrets

```bash
git clone https://github.com/g-freeks/listings-telegram-bot.git
cd listings-telegram-bot
cp env.example .env
```

Edit `.env`:

- `TELEGRAM_BOT_TOKEN` — from @BotFather.
- `CLAUDE_CODE_OAUTH_TOKEN` — run `claude setup-token` locally (opens a
  browser login), paste the resulting token here. The container has no
  interactive login, so this has to be generated ahead of time.

### 2. Create your buyer-profile config

```bash
cp config/config.json config.json
```

Edit `config.json` (this file is gitignored — it holds your real buyer
profile, financials, and the Telegram group's chat ID, never committed):

- `base_prompt` — the evaluator's instructions. The shipped example is tuned
  for Swedish listings (lagfart, pantbrev, ränteavdrag, etc.); adjust for a
  different market if needed.
- `buyer_profile`, `needs`, `no_gos`, `must_haves`, `nice_to_haves`,
  `commute_destinations` — your actual situation and priorities.
- `allowed_chat_ids` — leave as `[0]` for now; filled in below once you know
  your group's real chat ID.

### 3. Set up the Telegram bot and group

1. Message [@BotFather](https://t.me/BotFather), run `/setprivacy`, pick your
   bot, choose **Disable** — otherwise the bot can't see links or photos
   posted by others in the group.
2. Create a Telegram group and add your bot to it.
3. Send any message in the group, then fetch:
   ```bash
   curl -s "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates" | python3 -m json.tool
   ```
   Find `"chat": {"id": -100xxxxxxxxxx, ...}` — group/supergroup chat IDs are
   negative. Put that number in `config.json`'s `allowed_chat_ids`.

### 4. Build and run

Every push to `main` builds and publishes an image to GHCR
(`.github/workflows/docker-build.yml`), so you can just pull it instead of
building locally:

```bash
docker compose pull
docker compose up -d
```

Or build from source instead (e.g. if you've changed the Dockerfile or `app/`
code):

```bash
docker compose up -d --build
```

A from-source build downloads and installs Playwright's Chromium (~300 MB) and
takes a few minutes; pulling the prebuilt image is much faster. No host-side
`chown` or permission setup is needed either way —
`docker-entrypoint.sh` fixes ownership of the mounted volumes automatically on
every start, regardless of what user created them.

Check it's running:

```bash
docker compose logs -f
```

## Using it

In the Telegram group:

- **Send a listing link** (currently maklarhuset.se has full photo-gallery
  auto-fetch via Playwright; other sites fall back to a full-page screenshot)
  → the bot replies "Evaluating…", then a verdict (as a message, or a message
  + a `.md` attachment if the full evaluation is long).
- **Ask a follow-up question** → it reuses the same Claude session, so it
  remembers the earlier evaluation's context.
- **Send photos as an album** → collected with a 5-second debounce and
  analyzed together.
- **Commands**:
  - `/rule <text>` — add a standing instruction to the evaluator (e.g. "always
    check for a recent roof replacement").
  - `/config` — see the current config.json.
  - `/new` — start a fresh conversation (drops earlier context for this chat).
  - `/reload` — force re-read config.json and report any errors.
  - `/cost` — show cumulative evaluation cost.
  - `/help` — list commands.

Costs are logged to `data/cost_log.jsonl`; full evaluations are archived under
`data/evaluations/` (including `index.jsonl`, one line per evaluation).

## Updating config.json while running

`config.json` is re-read on every message, so editing it (or using `/rule`)
takes effect on the next message — no restart needed. If it's ever invalid
JSON or fails validation, the bot keeps using the last good version and
reports the error in chat.

## Security notes

The container runs non-root, with a read-only root filesystem, `cap_drop:
ALL` (plus the narrow capabilities `docker-entrypoint.sh` needs for its
startup ownership fix — see [CLAUDE.md](CLAUDE.md) for why), and memory/CPU
limits. The evaluating Claude process has no Bash/Write/Edit tools and is
denied from reading `/app/config` or `/proc`. Don't relax any of this without
understanding why it's there — [CLAUDE.md](CLAUDE.md)'s "Security rules"
section explains each one.

## Manual testing without Telegram

```bash
scripts/run_claude.sh "https://example.com/some-listing"
```

Runs the same `claude -p` contract the bot uses, against `./config.json`, for
quick iteration without going through Telegram.
