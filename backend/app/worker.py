from celery import Celery

from app.shared.config import Settings


def create_worker_app() -> Celery:
    settings = Settings.from_environment()
    return Celery("foreign_trade_worker", broker=settings.redis_url, backend=settings.redis_url)


celery_app = create_worker_app()
