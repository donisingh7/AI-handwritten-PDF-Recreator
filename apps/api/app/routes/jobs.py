from fastapi import APIRouter, Depends, HTTPException, status
from redis import Redis
from rq import Queue
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import JobStatus
from app.schemas import (
    DownloadUrlResponse,
    JobCreateRequest,
    JobCreateResponse,
    JobStatusResponse,
    PageStatusResponse,
    RetryPageResponse,
    StartJobResponse,
)
from app.services.job_service import JobService
from app.services.s3_service import S3Service
from app.workers.tasks import process_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


def get_queue(settings: Settings) -> Queue:
    redis_conn = Redis.from_url(settings.redis_url)
    return Queue(settings.rq_queue_name, connection=redis_conn)


@router.post("/create", response_model=JobCreateResponse)
def create_job(
    payload: JobCreateRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JobCreateResponse:
    if not payload.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are accepted.")
    if payload.file_size > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File exceeds {settings.max_upload_mb} MB upload limit.",
        )
    if payload.page_count > settings.max_pdf_pages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"PDF exceeds {settings.max_pdf_pages} page limit.",
        )

    service = JobService(settings)
    job = service.create_job(db, filename=payload.filename, page_count=payload.page_count)
    upload_url = S3Service(settings).create_presigned_upload_url(job.input_pdf_key)
    return JobCreateResponse(jobId=job.id, uploadUrl=upload_url, s3Key=job.input_pdf_key)


@router.post("/{job_id}/start", response_model=StartJobResponse)
def start_job(
    job_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StartJobResponse:
    service = JobService(settings)
    job = service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    if job.status not in {JobStatus.CREATED, JobStatus.UPLOADED, JobStatus.FAILED, JobStatus.PARTIALLY_FAILED}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Job is already {job.status}.")

    s3_service = S3Service(settings)
    if not s3_service.object_exists(job.input_pdf_key):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded PDF was not found in S3.")

    job.status = JobStatus.UPLOADED
    db.add(job)
    db.commit()

    queue = get_queue(settings)
    queue.enqueue(process_job, job.id, job_timeout="6h", result_ttl=86400, failure_ttl=86400)
    service.set_status(db, job, JobStatus.QUEUED)
    return StartJobResponse(status=JobStatus.QUEUED)


@router.get("/{job_id}/status", response_model=JobStatusResponse)
def get_job_status(
    job_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> JobStatusResponse:
    service = JobService(settings)
    job = service.get_job(db, job_id, with_pages=True)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    final_pdf_url = None
    if service.can_download(job):
        final_pdf_url = S3Service(settings).create_presigned_download_url(job.final_pdf_key)
    return service.build_status_response(job, final_pdf_url=final_pdf_url)


@router.get("/{job_id}/pages", response_model=list[PageStatusResponse])
def get_job_pages(
    job_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> list[PageStatusResponse]:
    service = JobService(settings)
    job = service.get_job(db, job_id, with_pages=True)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return service.build_page_responses(job.pages)


@router.post("/{job_id}/pages/{page_no}/retry", response_model=RetryPageResponse)
def retry_page(job_id: str, page_no: int, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    service = JobService(settings)
    job = service.get_job(db, job_id, with_pages=True)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    if page_no < 1 or page_no > job.page_count:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Page number is outside this job.")
    return RetryPageResponse(
        status="placeholder",
        message="Retry API is reserved for the MVP; page-specific retry enqueueing will be added next.",
    )


@router.get("/{job_id}/download-url", response_model=DownloadUrlResponse)
def get_download_url(
    job_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DownloadUrlResponse:
    service = JobService(settings)
    job = service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    if not service.can_download(job):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Final PDF is not ready.")
    return DownloadUrlResponse(url=S3Service(settings).create_presigned_download_url(job.final_pdf_key))
