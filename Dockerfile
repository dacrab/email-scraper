# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl procps \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
  && python -m playwright install --with-deps chromium

# Copy all relevant files
COPY config.py scraper.py app.py constants.py start.sh ./
COPY templates ./templates/
COPY static ./static/

RUN chmod +x /app/start.sh \
    && useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app /ms-playwright

USER appuser
EXPOSE 8000
CMD ["/app/start.sh"]
