FROM python:3.14.5-alpine AS builder

COPY --from=ghcr.io/astral-sh/uv:0.7.0 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY bot ./bot


FROM python:3.14.5-alpine

RUN apk add --no-cache ffmpeg opus
WORKDIR /app
COPY --from=builder /app/.venv ./.venv
COPY --from=builder /app/bot ./bot

RUN adduser -D -u 1000 botuser && chown -R botuser:botuser /app
USER botuser

ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "-u", "/app/bot/bot.py"]