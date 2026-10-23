# Build context: this directory (docker-compose and heroku.yml both use backend/ as context).

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
COPY data ./data

# --- Test image: `docker build --target test -t winddesk-test . && docker run --rm winddesk-test`
FROM base AS test
COPY requirements-dev.txt pyproject.toml ./
RUN pip install -r requirements-dev.txt
COPY tests ./tests
CMD ["sh", "-c", "ruff check app tests && pytest -q"]

# --- Runtime image (default target; what Heroku and docker-compose run)
FROM base AS runtime
RUN useradd --create-home --uid 10001 appuser
USER appuser
ENV PORT=8000
EXPOSE 8000
# Heroku injects $PORT at runtime.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
