import os
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from redis import Redis
from rq import SimpleWorker, Worker
from rq.timeouts import TimerDeathPenalty

from app.config import get_settings
from app.db import create_tables

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


class WorkerHealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"worker ok")

    def do_HEAD(self) -> None:
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return


class WindowsSimpleWorker(SimpleWorker):
    death_penalty_class = TimerDeathPenalty


def start_health_server_if_configured() -> None:
    port_value = os.environ.get("WORKER_HEALTH_PORT") or os.environ.get("PORT")
    if not port_value:
        return
    try:
        port = int(port_value)
    except ValueError:
        logger.warning("worker health server disabled: invalid port %r", port_value)
        return

    server = ThreadingHTTPServer(("0.0.0.0", port), WorkerHealthHandler)
    thread = threading.Thread(target=server.serve_forever, name="worker-health-server", daemon=True)
    thread.start()
    logger.info("worker health server listening on 0.0.0.0:%s", port)


def main() -> None:
    settings = get_settings()
    create_tables()
    start_health_server_if_configured()
    redis_conn = Redis.from_url(settings.redis_url)
    worker_cls = WindowsSimpleWorker if os.name == "nt" else Worker
    logger.info(
        "starting PDF worker queue=%s env=%s worker=%s",
        settings.rq_queue_name,
        settings.app_env,
        worker_cls.__name__,
    )
    worker = worker_cls([settings.rq_queue_name], connection=redis_conn)
    worker.work(with_scheduler=True, logging_level="INFO")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    main()
