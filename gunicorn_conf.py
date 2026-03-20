import os

# Gunicorn config variables
loglevel = "info"

# Workers: fixed at 2 by default for Railway containers (512MB RAM, 0.5 CPU).
# multiprocessing.cpu_count() returns HOST cpu count in containers, causing OOM.
# Override via WEB_CONCURRENCY env var if needed.
workers = int(os.getenv("WEB_CONCURRENCY", "2"))

bind = "0.0.0.0:8000"
worker_class = "uvicorn.workers.UvicornWorker"
