FROM node:22-slim

# Pin the Claude Code version (npm "stable" dist-tag as of 2026-10-10).
ARG CLAUDE_CODE_VERSION=2.1.287

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 \
      python3-pip \
      ca-certificates \
      gosu \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} \
    && npm cache clean --force

WORKDIR /app

# Shared, world-readable location so the non-root `node` user can run the
# Chromium binary installed here during the (root) build step.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --no-cache-dir --break-system-packages -r requirements.txt \
    && python3 -m playwright install --with-deps chromium

COPY --chown=node:node app/ /app/

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Starts as root so the entrypoint can fix volume ownership, then drops to
# `node` via gosu before running anything that touches network input.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python3", "/app/bot.py"]
