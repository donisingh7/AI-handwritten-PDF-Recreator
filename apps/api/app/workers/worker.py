import os

from redis import Redis
from rq import SimpleWorker, Worker
from rq.timeouts import TimerDeathPenalty

from app.config import get_settings
from app.db import create_tables


class WindowsSimpleWorker(SimpleWorker):
    death_penalty_class = TimerDeathPenalty


def main() -> None:
    settings = get_settings()
    create_tables()
    redis_conn = Redis.from_url(settings.redis_url)
    worker_cls = WindowsSimpleWorker if os.name == "nt" else Worker
    worker = worker_cls([settings.rq_queue_name], connection=redis_conn)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    main()
