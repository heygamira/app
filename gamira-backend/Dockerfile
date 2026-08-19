# Runtime image for the Gamira API.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv/gamira

# Dependencies first so application edits do not invalidate the install layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# The API never runs as root.
RUN useradd --system --create-home --uid 10001 gamira \
    && chown -R gamira:gamira /srv/gamira
USER gamira

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/health', timeout=2)"

# Migrations are applied by the deploy pipeline, not on container start, so a
# rolling restart cannot run two migrations at once.
# Shell form so $PORT (Cloud Run injects this; docker-compose does not, hence
# the :-8000 fallback) is expanded rather than passed through literally.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
