# zakvaska in a container. Built for amd64 and arm64 (a 64-bit Raspberry Pi)
# by .github/workflows/release.yml; `docker compose up -d` is all a user runs.
FROM python:3.12-slim

# Everything the notebook writes goes to /data, which compose keeps in a
# named volume. Inside the container the app always listens on 8420; the
# port you reach it on is the published one, set in docker-compose.yml.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ZAKVASKA_DATA_DIR=/data \
    ZAKVASKA_HOST=0.0.0.0 \
    ZAKVASKA_PORT=8420

WORKDIR /app

# Dependencies first, so editing the app does not reinstall them.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

# Not root. /data is created and owned here so that a fresh named volume,
# which takes its ownership from the image, is writable from the first start.
RUN useradd --uid 1000 --create-home zakvaska \
    && mkdir /data \
    && chown zakvaska:zakvaska /data
USER zakvaska
VOLUME /data
EXPOSE 8420

# /health answers 200 only when the database opens and /data is writable.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8420/health', timeout=4).status == 200 else 1)"]

# The app brings its own schema up to date as it starts (app/migrate.py),
# so there is no separate migration step to remember.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8420"]
