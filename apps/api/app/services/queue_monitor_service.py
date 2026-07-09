import logging

from redis import Redis
from rq import Queue
from rq.job import Job as RQJob
from rq.registry import FailedJobRegistry, StartedJobRegistry
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Job, JobStatus

logger = logging.getLogger(__name__)

ACTIVE_JOB_STATUSES = {
    JobStatus.QUEUED,
    JobStatus.RENDERING_PAGES,
    JobStatus.PROCESSING_PAGES,
    JobStatus.MERGING_PDF,
}


class QueueMonitorService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def sync_failed_job(self, db: Session, job: Job) -> bool:
        if job.status not in ACTIVE_JOB_STATUSES:
            return False

        try:
            redis_conn = Redis.from_url(self.settings.redis_url)
            queue = Queue(self.settings.rq_queue_name, connection=redis_conn)

            # RQ moves jobs abandoned by dead/restarted workers from Started to
            # Failed during cleanup. Running this on status polling prevents the
            # frontend from showing a stale in-progress state forever.
            StartedJobRegistry(queue.name, connection=redis_conn).cleanup()

            failed_registry = FailedJobRegistry(queue.name, connection=redis_conn)
            for rq_job_id in failed_registry.get_job_ids():
                rq_job = self._fetch_rq_job(redis_conn, rq_job_id)
                if rq_job is None or not self._matches_app_job(rq_job, job.id):
                    continue

                reason = self._failure_reason(rq_job)
                job.status = JobStatus.FAILED
                job.error = reason
                db.add(job)
                db.commit()
                db.refresh(job)
                logger.warning("job %s: synced failed RQ job %s to database", job.id, rq_job.id)
                return True
        except Exception as exc:
            logger.warning("job %s: could not sync queue status: %s", job.id, exc)
        return False

    def _fetch_rq_job(self, redis_conn: Redis, rq_job_id: str) -> RQJob | None:
        try:
            return RQJob.fetch(rq_job_id.split(":")[0], connection=redis_conn)
        except Exception:
            return None

    def _matches_app_job(self, rq_job: RQJob, app_job_id: str) -> bool:
        return bool(rq_job.args) and str(rq_job.args[0]) == app_job_id

    def _failure_reason(self, rq_job: RQJob) -> str:
        reason = "Worker stopped before completing this job. Redeploy the latest worker, then retry the job."
        if rq_job.exc_info:
            tail = rq_job.exc_info.strip().splitlines()[-1]
            reason = f"{reason} RQ: {tail[:220]}"
        return reason
