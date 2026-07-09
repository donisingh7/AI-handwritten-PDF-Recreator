from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings, get_settings
from app.models import Job, JobPage, JobStatus, PageStatus, ProcessingMode
from app.schemas import JobStatusResponse, PageStatusResponse
from app.services.model_options_service import DEFAULT_PREMIUM_MODEL_OPTION_ID
from app.services.s3_service import final_pdf_key, input_pdf_key


class JobService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def create_job(
        self,
        db: Session,
        filename: str,
        page_count: int,
        processing_mode: str,
        ai_provider: str | None = None,
        ai_model: str | None = None,
        model_option_id: str | None = None,
        cleanup_preset: str | None = None,
    ) -> Job:
        job = Job(
            filename=filename,
            page_count=page_count,
            processing_mode=processing_mode,
            ai_provider=ai_provider,
            ai_model=ai_model,
            model_option_id=model_option_id,
            cleanup_preset=cleanup_preset,
            input_pdf_key="",
        )
        db.add(job)
        db.flush()
        job.input_pdf_key = input_pdf_key(job.id)
        db.commit()
        db.refresh(job)
        return job

    def get_job(self, db: Session, job_id: str, with_pages: bool = False) -> Job | None:
        statement = select(Job).where(Job.id == job_id)
        if with_pages:
            statement = statement.options(selectinload(Job.pages))
        return db.execute(statement).scalar_one_or_none()

    def set_status(self, db: Session, job: Job, status: str, error: str | None = None) -> None:
        job.status = status
        job.error = error
        db.add(job)
        db.commit()
        db.refresh(job)

    def build_status_response(self, job: Job, final_pdf_url: str | None = None) -> JobStatusResponse:
        failed_pages = sorted(page.page_no for page in job.pages if page.status == PageStatus.FAILED)
        completed_pages = sum(1 for page in job.pages if page.status == PageStatus.COMPLETED)
        processing_mode = job.processing_mode or ProcessingMode.PREMIUM
        is_premium = processing_mode == ProcessingMode.PREMIUM
        return JobStatusResponse(
            jobId=job.id,
            status=job.status,
            processingMode=processing_mode,
            aiProvider=job.ai_provider or ("openai" if is_premium else None),
            aiModel=job.ai_model or ("gpt-image-2" if is_premium else None),
            modelOptionId=job.model_option_id or (DEFAULT_PREMIUM_MODEL_OPTION_ID if is_premium else None),
            cleanupPreset=job.cleanup_preset or (self.settings.cheap_cleanup_preset_normalized if processing_mode == ProcessingMode.CHEAP else None),
            pageCount=job.page_count,
            completedPages=completed_pages,
            failedPages=failed_pages,
            finalPdfUrl=final_pdf_url,
            error=job.error,
            createdAt=job.created_at,
            updatedAt=job.updated_at,
        )

    def build_page_responses(self, pages: list[JobPage]) -> list[PageStatusResponse]:
        return [
            PageStatusResponse(
                pageNo=page.page_no,
                status=page.status,
                sourceImageKey=page.source_image_key,
                generatedImageKey=page.generated_image_key,
                error=page.error,
                retryCount=page.retry_count,
            )
            for page in sorted(pages, key=lambda item: item.page_no)
        ]

    def expected_final_pdf_key(self, job_id: str) -> str:
        return final_pdf_key(job_id)

    def can_download(self, job: Job) -> bool:
        return job.status == JobStatus.COMPLETED and bool(job.final_pdf_key)
