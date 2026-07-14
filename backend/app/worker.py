from os import getenv

from celery import Celery


redis_url = getenv("REDIS_URL", "redis://redis:6379/0")
celery_app = Celery("foreign_trade_worker", broker=redis_url, backend=redis_url)
