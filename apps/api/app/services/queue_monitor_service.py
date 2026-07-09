import logging
from datetime import datetime, timezone

from redis import Redis
from rq import Queue
from rq.job import Job as RQJob
from rq.registry import DeferredJobRegistry, FailedJobRegistry, ScheduledJobRegistry, StartedJobRegistry
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

            active_ids = [
                *queue.job_ids,
                *StartedJobRegistry(queue.name, connection=redis_conn).get_job_ids(),
                *DeferredJobRegistry(queue.name, connection=redis_conn).get_job_ids(),
                *ScheduledJobRegistry(queue.name, connection=redis_conn).get_job_ids(),
            ]
            active_job = self._find_matching_job(redis_conn, active_ids, job.id)
            if active_job is not None:
                return False

            failed_ids = FailedJobRegistry(queue.name, connection=redis_conn).get_job_ids()
            failed_job = self._find_matching_job(redis_conn, failed_ids, job.id)
            failed_attempts = self._count_matching_jobs(redis_conn, failed_ids, job.id)
            if failed_job is not None:
                if self._auto_requeue(db, queue, job, failed_attempts):
                    return True
                self._mark_failed(db, job, self._failure_reason(failed_job))
                logger.warning("job %s: synced failed RQ job %s to database", job.id, failed_job.id)
                return True

            if job.status in ACTIVE_JOB_STATUSES and self._job_is_stale(job):
                if self._auto_requeue(db, queue, job, failed_attempts):
                    return True
                self._mark_failed(
                    db,
                    job,
                    "The background worker is no longer tracking this job. It may have crashed, restarted, or been redeployed before completion. Retry after the latest worker is deployed.",
                )
                logger.warning("job %s: marked failed because no RQ job is tracking it", job.id)
                return True
        except Exception as exc:
            logger.warning("job %s: could not sync queue status: %s", job.id, exc)
        return False

    def _auto_requeue(self, db: Session, queue: Queue, job: Job, failed_attempts: int) -> bool:
        if self.settings.job_auto_retry_limit <= 0 or failed_attempts > self.settings.job_auto_retry_limit:
            return False

        from app.workers.tasks import process_job

        retry_number = max(1, failed_attempts)
        queue.enqueue(process_job, job.id, job_timeout="6h", result_ttl=86400, failure_ttl=86400)
        job.status = JobStatus.QUEUED
        job.error = (
            "The worker stopped while processing this job. "
            f"Retrying automatically ({retry_number}/{self.settings.job_auto_retry_limit})."
        )
        job.updated_at = datetime.now(timezone.utc)
        db.add(job)
        db.commit()
        db.refresh(job)
        logger.warning(
            "job %s: automatically requeued after worker stop (%s/%s)",
            job.id,
            retry_number,
            self.settings.job_auto_retry_limit,
        )
        return True

    def _find_matching_job(self, redis_conn: Redis, rq_job_ids: list[str], app_job_id: str) -> RQJob | None:
        for rq_job_id in rq_job_ids:
            rq_job = self._fetch_rq_job(redis_conn, rq_job_id)
            if rq_job is not None and self._matches_app_job(rq_job, app_job_id):
                return rq_job
        return None

    def _count_matching_jobs(self, redis_conn: Redis, rq_job_ids: list[str], app_job_id: str) -> int:
        count = 0
        for rq_job_id in rq_job_ids:
            rq_job = self._fetch_rq_job(redis_conn, rq_job_id)
            if rq_job is not None and self._matches_app_job(rq_job, app_job_id):
                count += 1
        return count

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

    def _job_is_stale(self, job: Job) -> bool:
        if job.updated_at is None:
            return False
        updated_at = job.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - updated_at).total_seconds() > self.settings.job_stale_seconds

    def _mark_failed(self, db: Session, job: Job, reason: str) -> None:
        job.status = JobStatus.FAILED
        job.error = reason
        job.updated_at = datetime.now(timezone.utc)
        db.add(job)
        db.commit()
        db.refresh(job)
