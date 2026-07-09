import shutil
import logging
import time
import gc
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import Job, JobPage, JobStatus, PageStatus, ProcessingMode
from app.services.image_recreation_providers import ProviderFatalError, get_image_recreation_provider
from app.services.merge_service import MergeService
from app.services.model_options_service import DEFAULT_PREMIUM_MODEL_OPTION_ID, ModelOption, ModelOptionsService
from app.services.pdf_service import PDFService, PDFValidationError
from app.services.s3_service import S3Service, final_pdf_key, manifest_key, page_png_key

logger = logging.getLogger(__name__)


def process_job(job_id: str) -> None:
    job_started_at = time.monotonic()
    settings = get_settings()
    work_dir = Path(settings.local_work_dir) / job_id
    source_dir = work_dir / "source"
    premium_source_dir = work_dir / "premium_source"
    raw_dir = work_dir / "raw_generated"
    cleaned_dir = work_dir / "generated"
    final_dir = work_dir / "final"
    original_pdf_path = work_dir / "input" / "original.pdf"

    db = SessionLocal()
    try:
        logger.info("job %s: started", job_id)
        job = _load_job(db, job_id)
        if job is None:
            raise RuntimeError(f"Job {job_id} not found.")
        processing_mode = _processing_mode(job)
        logger.info("job %s: processing mode=%s", job.id, processing_mode)
        premium_model_option: ModelOption | None = None
        if processing_mode == ProcessingMode.PREMIUM:
            premium_model_option = _premium_model_option(job, settings)
            logger.info(
                "job %s: premium provider=%s model=%s modelOptionId=%s",
                job.id,
                premium_model_option.provider,
                premium_model_option.model,
                premium_model_option.id,
            )
            logger.info(
                "job %s: image recreation render config provider=%s preset=%s size=%sx%s format=%s outputQuality=%s",
                job.id,
                premium_model_option.provider,
                _provider_quality_preset(premium_model_option, settings),
                _provider_source_max_width(premium_model_option, settings),
                _provider_source_max_height(premium_model_option, settings),
                _provider_output_format(premium_model_option, settings),
                _provider_output_quality(premium_model_option, settings),
            )

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

        _ensure_page_records(db, job, actual_page_count)
        if processing_mode == ProcessingMode.CHEAP:
            _process_cheap_job_pages(
                db=db,
                job=job,
                settings=settings,
                pdf_service=pdf_service,
                s3=s3,
                original_pdf_path=original_pdf_path,
                source_dir=source_dir,
                cleaned_dir=cleaned_dir,
                final_dir=final_dir,
                actual_page_count=actual_page_count,
                job_started_at=job_started_at,
            )
            return

        stage_started_at = time.monotonic()
        logger.info("job %s: rendering %s PDF page(s)", job.id, actual_page_count)
        for page_no, source_path in pdf_service.iter_render_pages_to_png(
            original_pdf_path,
            source_dir,
            dpi=settings.pdf_render_dpi,
            max_pages=settings.max_pdf_pages,
        ):
            source_key = page_png_key(job.id, page_no, "source")
            s3.upload_file(source_path, source_key, "image/png")
            _mark_page_rendered(db, job, page_no, source_key)
            logger.info(
                "job %s page %s/%s: rendered and uploaded source image",
                job.id,
                page_no,
                actual_page_count,
            )
        page_records = _load_page_records(db, job)
        logger.info("job %s: rendered and uploaded PDF pages in %.1fs", job.id, time.monotonic() - stage_started_at)

        _set_job_status(db, job, JobStatus.PROCESSING_PAGES)
        generated_paths: dict[int, Path] = {}
        image_service = None
        prompt_service = None
        source_cleanup_service = None
        output_cleanup_service = None
        validation_service = None

        for page in sorted(page_records, key=lambda item: item.page_no):
            source_path = source_dir / f"page_{page.page_no:03d}.png"
            raw_format = _provider_output_format(premium_model_option, settings) if premium_model_option else settings.effective_openai_image_format
            cleaned_source_path = premium_source_dir / f"page_{page.page_no:03d}.png"
            cleaned_path = cleaned_dir / f"page_{page.page_no:03d}.png"
            try:
                page.status = PageStatus.PROCESSING
                page.error = None
                db.add(page)
                db.commit()

                from app.services.premium_output_cleanup_service import PremiumOutputCleanupService
                from app.services.premium_prompt_service import PremiumPromptService
                from app.services.premium_source_cleanup_service import PremiumSourceCleanupService
                from app.services.premium_style_validation_service import PremiumStyleValidationService

                if image_service is None:
                    if premium_model_option is None:
                        premium_model_option = _premium_model_option(job, settings)
                    image_service = get_image_recreation_provider(premium_model_option, settings)
                if prompt_service is None:
                    prompt_service = PremiumPromptService(settings)
                if source_cleanup_service is None:
                    source_cleanup_service = PremiumSourceCleanupService(settings)
                if output_cleanup_service is None:
                    output_cleanup_service = PremiumOutputCleanupService(settings)
                if validation_service is None:
                    validation_service = PremiumStyleValidationService(settings)

                source_cleanup_result = source_cleanup_service.clean_source(source_path, cleaned_source_path)
                logger.info(
                    "job %s page %s: source cleanup strategy=%s changed_pixel_ratio=%.4f",
                    job.id,
                    page.page_no,
                    source_cleanup_result.strategy,
                    source_cleanup_result.changed_pixel_ratio,
                )
                max_attempts = 1 + (
                    max(0, settings.premium_max_style_retries)
                    if settings.premium_style_retry_on_fail and settings.premium_style_validation_enabled
                    else 0
                )
                best_validation = None
                best_cleaned_path = cleaned_path
                style_warning = None
                for attempt_index in range(max_attempts):
                    attempt_no = attempt_index + 1
                    attempt_raw_path = raw_dir / f"page_{page.page_no:03d}_attempt_{attempt_no}.{raw_format}"
                    attempt_cleaned_path = cleaned_dir / f"page_{page.page_no:03d}_attempt_{attempt_no}.png"
                    prompt = prompt_service.build_prompt(page.page_no, retry_attempt=attempt_index)
                    logger.info(
                        "job %s page %s: premium style prompt mode=%s",
                        job.id,
                        page.page_no,
                        "retry_strict" if attempt_index else "standard_clean_a4",
                    )
                    page_started_at = time.monotonic()
                    logger.info(
                        "job %s page %s: requesting %s image recreation with %s attempt=%s/%s",
                        job.id,
                        page.page_no,
                        premium_model_option.provider if premium_model_option else "unknown",
                        premium_model_option.model if premium_model_option else "unknown",
                        attempt_no,
                        max_attempts,
                    )
                    image_service.recreate_page(
                        cleaned_source_path,
                        prompt,
                        attempt_raw_path,
                        page.page_no,
                        premium_model_option,
                    )
                    logger.info(
                        "job %s page %s: premium image recreation finished in %.1fs attempt=%s/%s",
                        job.id,
                        page.page_no,
                        time.monotonic() - page_started_at,
                        attempt_no,
                        max_attempts,
                    )
                    postprocess_started_at = time.monotonic()
                    cleanup_result = output_cleanup_service.clean_and_fit_to_a4(attempt_raw_path, attempt_cleaned_path)
                    logger.info(
                        "job %s page %s: output cleanup strategy=%s finished in %.1fs",
                        job.id,
                        page.page_no,
                        cleanup_result.strategy,
                        time.monotonic() - postprocess_started_at,
                    )
                    validation_result = validation_service.validate(attempt_cleaned_path)
                    best_validation = validation_result
                    best_cleaned_path = attempt_cleaned_path
                    if validation_result.passed:
                        style_warning = None
                        logger.info("job %s page %s: style validation passed attempt=%s", job.id, page.page_no, attempt_no)
                        break
                    style_warning = ",".join(validation_result.warnings)
                    logger.warning(
                        "job %s page %s: style validation failed attempt=%s/%s warnings=%s",
                        job.id,
                        page.page_no,
                        attempt_no,
                        max_attempts,
                        style_warning,
                    )
                    if attempt_no < max_attempts:
                        logger.info("job %s page %s: retrying premium generation for style cleanup", job.id, page.page_no)

                if best_cleaned_path != cleaned_path:
                    shutil.copyfile(best_cleaned_path, cleaned_path)
                if best_validation is not None and not best_validation.passed:
                    logger.warning("job %s page %s: keeping best attempt with style_warning=%s", job.id, page.page_no, style_warning)

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
                page.error = f"style_warning:{style_warning}" if style_warning else None
                db.add(page)
                _touch_job(job)
                db.commit()
                generated_paths[page.page_no] = cleaned_path
            except Exception as exc:
                logger.exception("job %s page %s: failed", job.id, page.page_no)
                page.status = PageStatus.FAILED
                page.error = str(exc)
                page.retry_count += 1
                db.add(page)
                _touch_job(job)
                db.commit()
                if isinstance(exc, ProviderFatalError):
                    raise

        failed_pages = [page.page_no for page in page_records if page.status == PageStatus.FAILED]
        if failed_pages:
            completed_pages = [page.page_no for page in page_records if page.status == PageStatus.COMPLETED]
            if completed_pages:
                job.status = JobStatus.PARTIALLY_FAILED
                job.error = f"Failed pages: {', '.join(str(page_no) for page_no in failed_pages)}"
                logger.info("job %s: partially failed after %.1fs", job.id, time.monotonic() - job_started_at)
            else:
                job.status = JobStatus.FAILED
                job.error = f"All pages failed: {', '.join(str(page_no) for page_no in failed_pages)}"
                logger.info("job %s: failed because all pages failed after %.1fs", job.id, time.monotonic() - job_started_at)
            _touch_job(job)
            db.add(job)
            db.commit()
            _upload_manifest(db, job.id, s3)
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
        _touch_job(job)
        db.add(job)
        db.commit()
        _upload_manifest(db, job.id, s3)
        logger.info("job %s: completed in %.1fs", job.id, time.monotonic() - job_started_at)
    except Exception as exc:
        logger.exception("job %s: failed", job_id)
        db.rollback()
        with SessionLocal() as failure_db:
            job = _load_job(failure_db, job_id)
            if job is not None:
                job.status = JobStatus.FAILED
                job.error = str(exc)
                _touch_job(job)
                failure_db.add(job)
                failure_db.commit()
            try:
                if job is not None:
                    _upload_manifest(failure_db, job.id, S3Service(settings))
            except Exception:
                pass
        raise
    finally:
        db.close()
        shutil.rmtree(work_dir, ignore_errors=True)


def _process_cheap_job_pages(
    db: Session,
    job: Job,
    settings,
    pdf_service: PDFService,
    s3: S3Service,
    original_pdf_path: Path,
    source_dir: Path,
    cleaned_dir: Path,
    final_dir: Path,
    actual_page_count: int,
    job_started_at: float,
) -> None:
    from app.services.cheap_cleanup_service import CheapCleanupService

    cleanup_preset = job.cleanup_preset or settings.cheap_cleanup_preset_normalized
    logger.info(
        "job %s: Cheap mode: OpenCV/Pillow cleanup only. OpenAI skipped. cleanup preset=%s",
        job.id,
        cleanup_preset,
    )
    cheap_cleanup_service = CheapCleanupService(
        cleanup_max_width=settings.cheap_mode_cleanup_max_width,
        cleanup_max_height=settings.cheap_mode_cleanup_max_height,
        enable_advanced_cleanup=settings.cheap_mode_enable_advanced_cleanup,
        preset=cleanup_preset,
        background_strength=settings.cheap_background_strength,
        contrast_strength=settings.cheap_contrast_strength,
        despeckle_strength=settings.cheap_despeckle_strength,
        remove_light_lines=settings.cheap_remove_light_lines,
        ink_darken=settings.cheap_ink_darken,
    )
    generated_keys: list[str] = []

    for page_no, source_path in pdf_service.iter_render_pages_to_png(
        original_pdf_path,
        source_dir,
        dpi=settings.cheap_mode_render_dpi,
        max_pages=settings.max_pdf_pages,
    ):
        cleaned_path = cleaned_dir / f"page_{page_no:03d}.png"
        generated_key = page_png_key(job.id, page_no, "generated")
        try:
            logger.info("job %s: Cheap mode processing page %s/%s", job.id, page_no, actual_page_count)
            source_key = page_png_key(job.id, page_no, "source")
            s3.upload_file(source_path, source_key, "image/png")
            _mark_page_rendered(db, job, page_no, source_key)
            logger.info("job %s page %s: Rendered page %s", job.id, page_no, page_no)

            _set_job_status(db, job, JobStatus.PROCESSING_PAGES)
            page = _mark_page_processing(db, job, page_no)
            cleanup_started_at = time.monotonic()
            logger.info("job %s page %s: Cleaning page %s", job.id, page_no, page_no)
            cleanup_result = cheap_cleanup_service.clean_page_to_a4(
                source_path,
                cleaned_path,
                settings.final_a4_width_px,
                settings.final_a4_height_px,
            )
            if cleanup_result.fallback_used:
                logger.warning("job %s page %s: Fallback normalize used for page %s", job.id, page_no, page_no)
            logger.info(
                (
                    "job %s page %s: cheap cleanup finished in %.1fs preset=%s strategy=%s "
                    "input=%sx%s output=%sx%s fallback=%s visual_change_score=%s changed_pixel_ratio=%s"
                ),
                job.id,
                page_no,
                time.monotonic() - cleanup_started_at,
                cleanup_preset,
                cleanup_result.strategy,
                cleanup_result.input_size[0],
                cleanup_result.input_size[1],
                cleanup_result.output_size[0],
                cleanup_result.output_size[1],
                cleanup_result.fallback_used,
                _format_metric(cleanup_result.visual_change_score),
                _format_metric(cleanup_result.changed_pixel_ratio),
            )
            if (
                cleanup_result.visual_change_score is not None
                and cleanup_result.visual_change_score < 0.012
                and cleanup_result.changed_pixel_ratio is not None
                and cleanup_result.changed_pixel_ratio < 0.025
            ):
                logger.warning("Cheap cleanup produced minimal visual change for page %s", page_no)

            s3.upload_file(cleaned_path, generated_key, "image/png")
            logger.info("job %s page %s: Uploaded generated page %s", job.id, page_no, page_no)
            page.generated_image_key = generated_key
            page.status = PageStatus.COMPLETED
            page.error = None
            db.add(page)
            _touch_job(job)
            db.commit()
            generated_keys.append(generated_key)
        finally:
            _cleanup_page_files(source_path, cleaned_path)
            logger.info("job %s page %s: Cleaned temp files for page %s", job.id, page_no, page_no)
            del cleaned_path, generated_key
            gc.collect()

    _set_job_status(db, job, JobStatus.MERGING_PDF)
    final_path = final_dir / "output.pdf"
    merge_started_at = time.monotonic()
    logger.info("job %s: merging %s generated page image(s) from S3 into PDF", job.id, len(generated_keys))
    MergeService().merge_s3_pngs_to_pdf(generated_keys, final_path, s3)
    logger.info("job %s: PDF merge finished in %.1fs", job.id, time.monotonic() - merge_started_at)

    key = final_pdf_key(job.id)
    upload_started_at = time.monotonic()
    s3.upload_file(final_path, key, "application/pdf")
    logger.info("job %s: final PDF uploaded in %.1fs", job.id, time.monotonic() - upload_started_at)
    job.final_pdf_key = key
    job.status = JobStatus.COMPLETED
    job.error = None
    _touch_job(job)
    db.add(job)
    db.commit()
    _upload_manifest(db, job.id, s3)
    logger.info("job %s: completed in %.1fs", job.id, time.monotonic() - job_started_at)


def _load_job(db: Session, job_id: str) -> Job | None:
    return db.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()


def _set_job_status(db: Session, job: Job, status: str) -> None:
    job.status = status
    _touch_job(job)
    db.add(job)
    db.commit()


def _touch_job(job: Job) -> None:
    job.updated_at = datetime.now(timezone.utc)


def _ensure_page_records(db: Session, job: Job, page_count: int) -> list[JobPage]:
    existing_pages = {
        page.page_no: page
        for page in db.execute(select(JobPage).where(JobPage.job_id == job.id)).scalars().all()
    }
    records: list[JobPage] = []
    for page_no in range(1, page_count + 1):
        page = existing_pages.get(page_no)
        if page is None:
            page = JobPage(job_id=job.id, page_no=page_no)
        page.source_image_key = None
        page.generated_image_key = None
        page.status = PageStatus.PENDING
        page.error = None
        page.retry_count = 0
        db.add(page)
        records.append(page)
    db.commit()
    return records


def _mark_page_rendered(db: Session, job: Job, page_no: int, source_key: str) -> JobPage:
    page = db.execute(select(JobPage).where(JobPage.job_id == job.id, JobPage.page_no == page_no)).scalar_one_or_none()
    if page is None:
        page = JobPage(job_id=job.id, page_no=page_no)
    page.source_image_key = source_key
    page.generated_image_key = None
    page.status = PageStatus.RENDERED
    page.error = None
    db.add(page)
    _touch_job(job)
    db.commit()
    return page


def _mark_page_processing(db: Session, job: Job, page_no: int) -> JobPage:
    page = db.execute(select(JobPage).where(JobPage.job_id == job.id, JobPage.page_no == page_no)).scalar_one()
    page.status = PageStatus.PROCESSING
    page.error = None
    db.add(page)
    _touch_job(job)
    db.commit()
    return page


def _cleanup_page_files(*paths: Path) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("could not delete temp page file %s", path)


def _load_page_records(db: Session, job: Job) -> list[JobPage]:
    return list(db.execute(select(JobPage).where(JobPage.job_id == job.id).order_by(JobPage.page_no)).scalars().all())


def _upload_manifest(db: Session, job_id: str, s3: S3Service) -> None:
    job = db.execute(select(Job).where(Job.id == job_id)).scalar_one()
    pages = db.execute(select(JobPage).where(JobPage.job_id == job_id).order_by(JobPage.page_no)).scalars().all()
    processing_mode = _processing_mode(job)
    is_premium = processing_mode == ProcessingMode.PREMIUM
    manifest: dict[str, Any] = {
        "jobId": job.id,
        "filename": job.filename,
        "status": job.status,
        "processingMode": processing_mode,
        "aiProvider": job.ai_provider or ("openai" if is_premium else None),
        "aiModel": job.ai_model or ("gpt-image-2" if is_premium else None),
        "modelOptionId": job.model_option_id or (DEFAULT_PREMIUM_MODEL_OPTION_ID if is_premium else None),
        "cleanupPreset": job.cleanup_preset or (s3.settings.cheap_cleanup_preset_normalized if processing_mode == ProcessingMode.CHEAP else None),
        "replicateQualityPreset": s3.settings.replicate_quality_preset_normalized if job.ai_provider == "replicate" else None,
        "sourceMaxWidth": _replicate_manifest_source_max_width(job, s3.settings),
        "sourceMaxHeight": _replicate_manifest_source_max_height(job, s3.settings),
        "outputFormat": _replicate_manifest_output_format(job, s3.settings),
        "outputQuality": _replicate_manifest_output_quality(job, s3.settings),
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


def _premium_model_option(job: Job, settings) -> ModelOption:
    option_id = job.model_option_id or DEFAULT_PREMIUM_MODEL_OPTION_ID
    service = ModelOptionsService(settings)
    option = service.get_option(option_id)
    if option is None:
        raise RuntimeError(f"Unknown premium model option: {option_id}")
    if not option.enabled:
        reason = option.disabled_reason or "The provider is not configured on this backend."
        raise RuntimeError(f"{option.label} is not available: {reason}")
    return option


def _provider_quality_preset(model_option: ModelOption, settings) -> str:
    if model_option.provider == "openai":
        return settings.openai_cost_mode_normalized
    if model_option.provider == "replicate":
        return settings.replicate_quality_preset_normalized
    return "provider_default"


def _provider_source_max_width(model_option: ModelOption, settings) -> int | str:
    if model_option.provider == "openai":
        return settings.effective_openai_source_max_width_px
    if model_option.provider == "replicate":
        return int(settings.effective_replicate_quality_config["source_max_width"])
    return "provider_default"


def _provider_source_max_height(model_option: ModelOption, settings) -> int | str:
    if model_option.provider == "openai":
        return settings.effective_openai_source_max_height_px
    if model_option.provider == "replicate":
        return int(settings.effective_replicate_quality_config["source_max_height"])
    return "provider_default"


def _provider_output_format(model_option: ModelOption, settings) -> str:
    if model_option.provider == "openai":
        return settings.effective_openai_image_format
    if model_option.provider == "replicate":
        return str(settings.effective_replicate_quality_config["output_format"])
    return "png"


def _provider_output_quality(model_option: ModelOption, settings) -> int | str:
    if model_option.provider == "openai":
        return settings.effective_openai_image_quality
    if model_option.provider == "replicate":
        return int(settings.effective_replicate_quality_config["output_quality"])
    return "provider_default"


def _replicate_manifest_source_max_width(job: Job, settings) -> int | None:
    if job.ai_provider != "replicate":
        return None
    return int(settings.effective_replicate_quality_config["source_max_width"])


def _replicate_manifest_source_max_height(job: Job, settings) -> int | None:
    if job.ai_provider != "replicate":
        return None
    return int(settings.effective_replicate_quality_config["source_max_height"])


def _replicate_manifest_output_format(job: Job, settings) -> str | None:
    if job.ai_provider != "replicate":
        return None
    return str(settings.effective_replicate_quality_config["output_format"])


def _replicate_manifest_output_quality(job: Job, settings) -> int | None:
    if job.ai_provider != "replicate":
        return None
    return int(settings.effective_replicate_quality_config["output_quality"])


def _format_metric(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.4f}"
