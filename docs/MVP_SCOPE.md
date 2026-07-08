# MVP Scope

## In Scope

- Single PDF upload.
- Maximum 100 pages.
- Private S3 storage with presigned upload and download URLs.
- PostgreSQL-backed job and page tracking.
- Redis Queue background processing.
- PyMuPDF rendering of every page.
- Premium Mode with OpenAI Image API recreation per page.
- Cheap Mode with OpenCV/Pillow cleanup only and no OpenAI image call.
- Sequential processing by default to reduce rate-limit pressure.
- Printable A4 post-processing at `2480x3508` and `300` DPI.
- Final PDF merge only after all pages complete.
- Job status polling, page count, completed count, failed pages, and final download UI.

## Out Of Scope For MVP

- Authentication.
- Payments.
- Multi-file upload.
- Page preview and manual approval.
- Page-specific retry implementation.
- Automatic typo correction.
- Guaranteed perfect OCR-level content preservation.
- High-concurrency processing.

## Visual Acceptance Criteria

A completed job should satisfy:

- input page order is preserved
- each output page has a clean white portrait A4 background
- body handwriting appears blue
- headings, underlines, page numbers, dates, captions, and diagram labels appear black where the model follows the prompt
- Cheap Mode preserves the original handwriting and prioritizes readable cleaned scans over AI recreation
- final PNG pages are normalized to `2480x3508`
- final PDF is created from normalized PNGs
- scanner shadows, ruled lines, stains, grey tint, borders, and tiny spots are reduced by prompt plus post-processing

## Current Model Limitations

The image model may still alter hard-to-read text, diagram labels, line placement, or spelling. The MVP stores page-level failures and exposes a retry placeholder, but a production workflow should add preview, manual acceptance, and page-specific retry before users rely on the output for final submission.
