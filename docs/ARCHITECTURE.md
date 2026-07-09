# Architecture

## Request Flow

1. The user selects Premium Mode or Cheap Mode, then selects one PDF in the Next.js app.
2. The browser validates file type, size, and page count with `pdf-lib`.
3. The web app calls `POST /jobs/create`.
4. FastAPI creates a PostgreSQL job row and returns a presigned S3 upload URL.
5. The browser uploads the original PDF directly to private S3.
6. The web app calls `POST /jobs/{job_id}/start`.
7. FastAPI verifies the S3 object exists and enqueues an RQ job.
8. The worker downloads the original PDF, validates it again, renders pages, processes each page, and writes final outputs.
9. The job page polls `GET /jobs/{job_id}/status` and `GET /jobs/{job_id}/pages`.
10. Completed jobs expose a presigned final PDF download URL.

## Backend Modules

- `routes/jobs.py`: API endpoints for job creation, start, status, pages, retry placeholder, and download URL.
- `services/s3_service.py`: S3 key naming, presigned URLs, upload, download, JSON manifest writes.
- `services/pdf_service.py`: PDF validation and PyMuPDF rendering.
- `services/openai_image_service.py`: centralized prompt template and OpenAI Image API call for Premium Mode.
- `services/cheap_cleanup_service.py`: OpenCV/Pillow cleanup and A4 normalization for Cheap Mode.
- `services/image_postprocess_service.py`: background whitening, tiny noise removal, A4 canvas fitting, PNG export.
- `services/merge_service.py`: final A4 PDF creation from ordered cleaned PNGs.
- `workers/tasks.py`: end-to-end job orchestration and status updates.

## Storage Keys

```text
jobs/{jobId}/input/original.pdf
jobs/{jobId}/source/page_001.png
jobs/{jobId}/source/page_002.png
jobs/{jobId}/generated/page_001.png
jobs/{jobId}/generated/page_002.png
jobs/{jobId}/final/output.pdf
jobs/{jobId}/manifest.json
```

Page numbers are always zero-padded and merges are sorted by numeric `page_no`.

## Status Lifecycle

```text
created -> uploaded -> queued -> rendering_pages -> processing_pages -> merging_pdf -> completed
```

If page generation fails for any page, the job becomes `partially_failed` and no final PDF is generated. Fatal failures become `failed`.

## Printable A4 Pipeline

Premium Mode treats the model output as an intermediate image. The worker performs:

1. source PDF page render to PNG at 200 DPI
2. OpenAI image edit/recreation using the rendered source page
3. white background normalization
4. tiny noise removal
5. aspect-ratio-preserving fit onto `2480x3508` white A4 canvas
6. cleaned PNG upload to S3
7. PDF merge from cleaned PNGs at A4 page size

This keeps the final PDF printable even when the image model returns a lower-resolution portrait PNG.

Cheap Mode skips the OpenAI call. It is memory-optimized and performs one page at a time:

1. source PDF page render to PNG at `CHEAP_MODE_RENDER_DPI`
2. source PNG upload to S3
3. local scan cleanup with OpenCV/Pillow using bounded intermediate dimensions
4. fallback A4 normalization if advanced cleanup fails
5. aspect-ratio-preserving fit onto `2480x3508` white A4 canvas
6. cleaned PNG upload to S3
7. per-page temp file deletion and garbage collection
8. PDF merge from generated page images at A4 page size

`manifest.json` includes `processingMode`, and old jobs without a stored mode are treated as `premium`.
