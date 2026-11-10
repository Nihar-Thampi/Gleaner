# Gleaner API + scheduler worker, with headless Chromium for JavaScript sites.
# Bookworm (Debian 12): Playwright's --with-deps installer supports it.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY requirements.txt .
# Playwright's bundled Node.js driver needs libatomic1, which the slim image lacks.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libatomic1 \
 && pip install -r requirements.txt \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

COPY . .

# SQLite database lives here; mount a volume to keep it across restarts.
VOLUME /app/data
EXPOSE 8000

# Seed the demo data on first start (empty volume), then serve.
CMD ["sh", "-c", "if [ ! -f data/gleaner.db ] && [ \"${SEED_ON_START:-1}\" = 1 ]; then python seed.py; fi && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
