import shutil
import logging
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import Job, JobPage, JobStatus, PageStatus, ProcessingMode
from app.services.cheap_cleanup_service import CheapCleanupService
from app.services.image_postprocess_service import ImagePostprocessService
from app.services.merge_service import MergeService
from app.services.openai_image_service import OpenAIImageService
from app.services.pdf_service import PDFService, PDFValidationError
from app.services.s3_service import S3Service, final_pdf_key, manifest_key, page_png_key

logger = logging.getLogger(__name__)


def process_job(job_id: str) -> None:
    job_started_at = time.monotonic()
    settings = get_settings()
    work_dir = Path(settings.local_work_dir) / job_id
    source_dir = work_dir / "source"
    raw_dir = work_dir / "raw_generated"
    cleaned_dir = work_dir / "generated"
    final_dir = work_dir / "final"
    original_pdf_path = work_dir / "input" / "original.pdf"

    db = SessionLocal()
    try:
        logger.info("job %s: started", job_id)
        logger.info(
            "job %s: OpenAI cost mode=%s size=%s quality=%s format=%s source_max=%sx%s",
            job_id,
            settings.openai_cost_mode_normalized,
            settings.effective_openai_image_size,
            settings.effective_openai_image_quality,
            settings.effective_openai_image_format,
            settings.effective_openai_source_max_width_px,
            settings.effective_openai_source_max_height_px,
        )
        job = _load_job(db, job_id)
        if job is None:
            raise RuntimeError(f"Job {job_id} not found.")

        _set_job_status(db, job, JobStatus.RENDERING_PAGES)
        stage_started_at = time.monotonic()
        logger.info("job %s: downloading original PDF from S3", job.id)
        s3 = S3Service(settings)
        s3.download_file(job.input_pdf_key, original_pdf_path)
        logger.info("job %s: original PDF downloaded in %.1fs", job.id, time.monotonic() - stage_started_at)

        pdf_service = PDFService()
        actual_page_count = pdf_service.validate_pdf(original_pdf_path, settings.max_pdf_pages)
        if actual_page_count != job.page_count:
            raise PDFValidationError(
                f"Uploaded PDF has {actual_page_count} pages, but job was created for {job.page_count} pages."
            )

        stage_started_at = time.monotonic()
        logger.info("job %s: rendering %s PDF page(s)", job.id, actual_page_count)
        source_paths = pdf_service.render_pages_to_png(
            original_pdf_path,
            source_dir,
            dpi=settings.pdf_render_dpi,
            max_pages=settings.max_pdf_pages,
        )
        logger.info("job %s: rendered PDF pages in %.1fs", job.id, time.monotonic() - stage_started_at)

        page_records = _create_or_update_page_records(db, job, source_paths, s3)
        logger.info("job %s: uploaded source page images", job.id)

        _set_job_status(db, job, JobStatus.PROCESSING_PAGES)
        generated_paths: dict[int, Path] = {}
        image_service = OpenAIImageService(settings)
        postprocess_service = ImagePostprocessService(settings)
        cheap_cleanup_service = CheapCleanupService()

        for page in sorted(page_records, key=lambda item: item.page_no):
            source_path = source_dir / f"page_{page.page_no:03d}.png"
            raw_path = raw_dir / f"page_{page.page_no:03d}.{settings.effective_openai_image_format}"
            cleaned_path = cleaned_dir / f"page_{page.page_no:03d}.png"
            try:
                page.status = PageStatus.PROCESSING
                page.error = None
                db.add(page)
                db.commit()

                if _processing_mode(job) == ProcessingMode.CHEAP:
                    cleanup_started_at = time.monotonic()
                    logger.info("job %s page %s: running cheap cleanup without OpenAI", job.id, page.page_no)
                    cheap_cleanup_service.clean_page_to_a4(
                        source_path,
                        cleaned_path,
                        settings.final_a4_width_px,
                        settings.final_a4_height_px,
                    )
                    logger.info(
                        "job %s page %s: cheap cleanup finished in %.1fs",
                        job.id,
                        page.page_no,
                        time.monotonic() - cleanup_started_at,
                    )
                else:
                    page_started_at = time.monotonic()
                    logger.info("job %s page %s: requesting OpenAI image recreation", job.id, page.page_no)
                    image_service.recreate_page(source_path, raw_path, page.page_no)
                    logger.info(
                        "job %s page %s: OpenAI image recreation finished in %.1fs",
                        job.id,
                        page.page_no,
                        time.monotonic() - page_started_at,
                    )
                    postprocess_started_at = time.monotonic()
                    postprocess_service.clean_and_fit_to_a4(raw_path, cleaned_path)
                    logger.info(
                        "job %s page %s: image post-processing finished in %.1fs",
                        job.id,
                        page.page_no,
                        time.monotonic() - postprocess_started_at,
                    )

                generated_key = page_png_key(job.id, page.page_no, "generated")
                upload_started_at = time.monotonic()
                s3.upload_file(cleaned_path, generated_key, "image/png")
                logger.info(
                    "job %s page %s: generated PNG uploaded in %.1fs",
                    job.id,
                    page.page_no,
                    time.monotonic() - upload_started_at,
                )
                page.generated_image_key = generated_key
                page.status = PageStatus.COMPLETED
                page.error = None
                db.add(page)
                db.commit()
                generated_paths[page.page_no] = cleaned_path
            except Exception as exc:
                logger.exception("job %s page %s: failed", job.id, page.page_no)
                page.status = PageStatus.FAILED
                page.error = str(exc)
                page.retry_count += 1
                db.add(page)
                db.commit()

        failed_pages = [page.page_no for page in page_records if page.status == PageStatus.FAILED]
        if failed_pages:
            job.status = JobStatus.PARTIALLY_FAILED
            job.error = f"Failed pages: {', '.join(str(page_no) for page_no in failed_pages)}"
            db.add(job)
            db.commit()
            _upload_manifest(db, job.id, s3)
            logger.info("job %s: partially failed after %.1fs", job.id, time.monotonic() - job_started_at)
            return

        _set_job_status(db, job, JobStatus.MERGING_PDF)
        ordered_images = [generated_paths[page_no] for page_no in sorted(generated_paths)]
        final_path = final_dir / "output.pdf"
        merge_started_at = time.monotonic()
        logger.info("job %s: merging %s page image(s) into PDF", job.id, len(ordered_images))
        MergeService().merge_pngs_to_pdf(ordered_images, final_path)
        logger.info("job %s: PDF merge finished in %.1fs", job.id, time.monotonic() - merge_started_at)

        key = final_pdf_key(job.id)
        upload_started_at = time.monotonic()
        s3.upload_file(final_path, key, "application/pdf")
        logger.info("job %s: final PDF uploaded in %.1fs", job.id, time.monotonic() - upload_started_at)
        job.final_pdf_key = key
        job.status = JobStatus.COMPLETED
        job.error = None
        db.add(job)
        db.commit()
        _upload_manifest(db, job.id, s3)
        logger.info("job %s: completed in %.1fs", job.id, time.monotonic() - job_started_at)
    except Exception as exc:
        logger.exception("job %s: failed", job_id)
        job = _load_job(db, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.error = str(exc)
            db.add(job)
            db.commit()
            try:
                _upload_manifest(db, job.id, S3Service(settings))
            except Exception:
                pass
        raise
    finally:
        db.close()
        shutil.rmtree(work_dir, ignore_errors=True)


def _load_job(db: Session, job_id: str) -> Job | None:
    return db.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()


def _set_job_status(db: Session, job: Job, status: str) -> None:
    job.status = status
    db.add(job)
    db.commit()
    db.refresh(job)


def _create_or_update_page_records(db: Session, job: Job, source_paths: list[Path], s3: S3Service) -> list[JobPage]:
    records: list[JobPage] = []
    for source_path in source_paths:
        page_no = int(source_path.stem.split("_")[1])
        source_key = page_png_key(job.id, page_no, "source")
        s3.upload_file(source_path, source_key, "image/png")

        page = db.execute(
            select(JobPage).where(JobPage.job_id == job.id, JobPage.page_no == page_no)
        ).scalar_one_or_none()
        if page is None:
            page = JobPage(job_id=job.id, page_no=page_no)
        page.source_image_key = source_key
        page.status = PageStatus.RENDERED
        page.error = None
        db.add(page)
        records.append(page)
    db.commit()
    for page in records:
        db.refresh(page)
    return records


def _upload_manifest(db: Session, job_id: str, s3: S3Service) -> None:
    job = db.execute(select(Job).where(Job.id == job_id)).scalar_one()
    pages = db.execute(select(JobPage).where(JobPage.job_id == job_id).order_by(JobPage.page_no)).scalars().all()
    manifest: dict[str, Any] = {
        "jobId": job.id,
        "filename": job.filename,
        "status": job.status,
        "processingMode": _processing_mode(job),
        "pageCount": job.page_count,
        "inputPdfKey": job.input_pdf_key,
        "finalPdfKey": job.final_pdf_key,
        "error": job.error,
        "pages": [
            {
                "pageNo": page.page_no,
                "status": page.status,
                "sourceImageKey": page.source_image_key,
                "generatedImageKey": page.generated_image_key,
                "error": page.error,
                "retryCount": page.retry_count,
            }
            for page in pages
        ],
    }
    s3.put_json(manifest_key(job_id), manifest)


def _processing_mode(job: Job) -> str:
    if job.processing_mode in ProcessingMode.VALUES:
        return job.processing_mode
    return ProcessingMode.PREMIUM
