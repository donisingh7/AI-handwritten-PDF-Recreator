import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import Job, JobPage, JobStatus, PageStatus
from app.services.image_postprocess_service import ImagePostprocessService
from app.services.merge_service import MergeService
from app.services.openai_image_service import OpenAIImageService
from app.services.pdf_service import PDFService, PDFValidationError
from app.services.s3_service import S3Service, final_pdf_key, manifest_key, page_png_key


def process_job(job_id: str) -> None:
    settings = get_settings()
    work_dir = Path(settings.local_work_dir) / job_id
    source_dir = work_dir / "source"
    raw_dir = work_dir / "raw_generated"
    cleaned_dir = work_dir / "generated"
    final_dir = work_dir / "final"
    original_pdf_path = work_dir / "input" / "original.pdf"

    db = SessionLocal()
    try:
        job = _load_job(db, job_id)
        if job is None:
            raise RuntimeError(f"Job {job_id} not found.")

        _set_job_status(db, job, JobStatus.RENDERING_PAGES)
        s3 = S3Service(settings)
        s3.download_file(job.input_pdf_key, original_pdf_path)

        pdf_service = PDFService()
        actual_page_count = pdf_service.validate_pdf(original_pdf_path, settings.max_pdf_pages)
        if actual_page_count != job.page_count:
            raise PDFValidationError(
                f"Uploaded PDF has {actual_page_count} pages, but job was created for {job.page_count} pages."
            )

        source_paths = pdf_service.render_pages_to_png(
            original_pdf_path,
            source_dir,
            dpi=settings.pdf_render_dpi,
            max_pages=settings.max_pdf_pages,
        )

        page_records = _create_or_update_page_records(db, job, source_paths, s3)

        _set_job_status(db, job, JobStatus.PROCESSING_PAGES)
        generated_paths: dict[int, Path] = {}
        image_service = OpenAIImageService(settings)
        postprocess_service = ImagePostprocessService(settings)

        for page in sorted(page_records, key=lambda item: item.page_no):
            source_path = source_dir / f"page_{page.page_no:03d}.png"
            raw_path = raw_dir / f"page_{page.page_no:03d}.{settings.openai_image_format}"
            cleaned_path = cleaned_dir / f"page_{page.page_no:03d}.png"
            try:
                page.status = PageStatus.PROCESSING
                page.error = None
                db.add(page)
                db.commit()

                image_service.recreate_page(source_path, raw_path, page.page_no)
                postprocess_service.clean_and_fit_to_a4(raw_path, cleaned_path)

                generated_key = page_png_key(job.id, page.page_no, "generated")
                s3.upload_file(cleaned_path, generated_key, "image/png")
                page.generated_image_key = generated_key
                page.status = PageStatus.COMPLETED
                page.error = None
                db.add(page)
                db.commit()
                generated_paths[page.page_no] = cleaned_path
            except Exception as exc:
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
            return

        _set_job_status(db, job, JobStatus.MERGING_PDF)
        ordered_images = [generated_paths[page_no] for page_no in sorted(generated_paths)]
        final_path = final_dir / "output.pdf"
        MergeService().merge_pngs_to_pdf(ordered_images, final_path)

        key = final_pdf_key(job.id)
        s3.upload_file(final_path, key, "application/pdf")
        job.final_pdf_key = key
        job.status = JobStatus.COMPLETED
        job.error = None
        db.add(job)
        db.commit()
        _upload_manifest(db, job.id, s3)
    except Exception as exc:
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
