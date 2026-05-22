FROM python:3.14.5-alpine AS builder

COPY --from=ghcr.io/astral-sh/uv:0.7.0 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY bot ./bot

RUN uv sync --frozen --no-dev


FROM python:3.14.5-alpine

RUN apk add --no-cache ffmpeg
WORKDIR /app
COPY --from=builder /app/.venv ./.venv
COPY --from=builder /app/bot ./bot

RUN adduser -D -u 1000 botuser && chown -R botuser:botuser /app
USER botuser

ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "-u", "./bot/bot.py"]