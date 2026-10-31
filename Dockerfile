FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    VALO_DATA_DIR=/data

WORKDIR /app

# ca-certificates is required for the HTTPS calls to the HenrikDev API,
# tzdata keeps the container clock aligned with the NAS timezone.
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY app.py ./
COPY valorant ./valorant
COPY static ./static

RUN mkdir -p /data

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3).read()"]

STOPSIGNAL SIGTERM

# The container must listen on all interfaces so the NAS can publish the port.
CMD ["python3", "app.py", "--host", "0.0.0.0", "--port", "8765", "--no-browser"]
