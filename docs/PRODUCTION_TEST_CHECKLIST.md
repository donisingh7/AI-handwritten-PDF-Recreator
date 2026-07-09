# Production Test Checklist

Use this checklist after deploying the API and worker to AWS Lightsail.

## API Health

- Local server health:

  ```bash
  curl http://127.0.0.1:8000/health
  ```

- Public HTTPS health:

  ```bash
  curl https://api.yourdomain.com/health
  ```

Expected response:

```json
{"status":"ok"}
```

## Logs

- API logs:

  ```bash
  sudo journalctl -u handpdf-api -f
  ```

- Worker logs:

  ```bash
  sudo journalctl -u handpdf-worker -f
  ```

- Confirm the worker is listening on the Redis queue:

  ```text
  pdf-jobs
  ```

## Upload And Processing Tests

Run these from the Vercel frontend after `NEXT_PUBLIC_API_URL` points to the AWS API:

- Cheap Mode 1-page PDF
- Premium Mode 1-page PDF
- Cheap Mode 5-page PDF
- Cheap Mode 20-page PDF
- Cheap Mode 50-page PDF

For Cheap Mode, confirm logs contain:

```text
Cheap mode: OpenCV/Pillow cleanup only. OpenAI skipped.
Cheap mode processing page X/Y
Uploaded generated page X
Cleaned temp files for page X
```

For Premium Mode, confirm the OpenAI image recreation logs appear only when Premium Mode is selected.

## S3 Checks

For a completed job, verify these objects exist:

```text
jobs/{jobId}/source/page_001.png
jobs/{jobId}/generated/page_001.png
jobs/{jobId}/final/output.pdf
jobs/{jobId}/manifest.json
```

## Supabase Checks

In the Supabase `jobs` table:

- `status` becomes `completed`
- `processing_mode` is `cheap` or `premium`
- `final_pdf_key` is populated
- `error` is empty for successful jobs

In the `job_pages` table:

- Every page has status `completed`
- `source_image_key` is populated
- `generated_image_key` is populated

## Final PDF Checks

- Download link appears in the frontend.
- Final PDF opens.
- Page order matches the original PDF.
- Output is printable A4.
- Cheap Mode preserves readable handwriting and diagrams.
- Premium Mode provides the higher-quality AI recreation path.

## Troubleshooting Quick Checks

- API service:

  ```bash
  sudo systemctl status handpdf-api --no-pager
  sudo journalctl -u handpdf-api -n 100 --no-pager
  ```

- Worker service:

  ```bash
  sudo systemctl status handpdf-worker --no-pager
  sudo journalctl -u handpdf-worker -n 100 --no-pager
  ```

- Restart services:

  ```bash
  sudo systemctl restart handpdf-api
  sudo systemctl restart handpdf-worker
  ```

- Common failure areas:
  - Missing env vars in `/etc/handpdf.env`
  - Redis queue mismatch; API and worker must both use `RQ_QUEUE_NAME=pdf-jobs`
  - S3 bucket/IAM permission issue
  - Supabase `DATABASE_URL` password needs URL encoding
  - Nginx 502 because API is not running on `127.0.0.1:8000`
  - SSL/DNS not pointing to the Lightsail public IP
  - Vercel CORS URL mismatch
  - Cheap Mode still needs more RAM for large PDFs
