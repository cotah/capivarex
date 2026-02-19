import multiprocessing

# Gunicorn config variables
loglevel = "info"
workers = multiprocessing.cpu_count() * 2 + 1
bind = "0.0.0.0:8000"
worker_class = "uvicorn.workers.UvicornWorker"
