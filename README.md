# AI Handwritten PDF Recreator

Full-stack MVP for converting a scanned practical/notebook PDF into a clean, printable A4 handwritten-style PDF.

The system accepts exactly one PDF per job, uploads it directly to private S3 through a presigned URL, renders every page, processes each page in either Premium Mode or Cheap Mode, normalizes each page onto a 300-DPI A4 canvas, and merges the cleaned pages into the final printable PDF.

## Architecture

- `apps/web`: Next.js, TypeScript, Tailwind CSS, `pdf-lib` client-side validation.
- `apps/api`: FastAPI API, SQLAlchemy models, S3 services, RQ job enqueueing.
- Worker: Redis Queue worker that renders, generates, post-processes, merges, and updates job/page status.
- Storage: private S3 bucket with presigned upload/download URLs.
- Database: PostgreSQL tables created automatically at startup for MVP local dev.
- Queue: Redis + RQ.

## Local Setup

1. Copy API env:

   ```bash
   cp apps/api/.env.example apps/api/.env
   ```

2. Fill in S3 settings in `apps/api/.env` or export them before using Docker Compose:

   ```bash
   AWS_ACCESS_KEY_ID=<aws_access_key_id>
   AWS_SECRET_ACCESS_KEY=<aws_secret_access_key>
   AWS_REGION=<aws_region>
   S3_BUCKET=<private_s3_bucket_name>
   ```

3. Add `OPENAI_API_KEY` later when you are ready to run real page recreation. The code is already wired for it, but no key is committed or generated here.

4. Start backend dependencies, API, and worker:

   ```bash
   docker compose up --build
   ```

5. Run the frontend separately:

   ```bash
   cd apps/web
   cp .env.example .env.local
   npm install
   npm run dev
   ```

6. Open `http://localhost:3000`.

## Environment Variables

API:

- `DATABASE_URL`
- `REDIS_URL`
- `RQ_QUEUE_NAME`
- `CORS_ORIGINS`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`
- `S3_BUCKET`
- `S3_ENDPOINT_URL`
- `MAX_PDF_PAGES`
- `MAX_UPLOAD_MB`
- `PDF_RENDER_DPI`
- `OPENAI_API_KEY`
- `OPENAI_IMAGE_MODEL`
- `OPENAI_IMAGE_SIZE`
- `OPENAI_IMAGE_QUALITY`
- `OPENAI_IMAGE_FORMAT`
- `DEFAULT_PROCESSING_MODE`
- `FINAL_A4_WIDTH_PX`
- `FINAL_A4_HEIGHT_PX`
- `FINAL_PRINT_DPI`

Frontend:

- `NEXT_PUBLIC_API_URL`
- `NEXT_PUBLIC_MAX_PDF_PAGES`
- `NEXT_PUBLIC_MAX_UPLOAD_MB`

## Image Generation And Print Pipeline

Premium Mode is the existing AI image recreation pipeline. It uses the OpenAI Image API to recreate each rendered page as a clean handwritten A4 page, then performs post-processing and PDF merge.

Cheap Mode is an OpenCV/Pillow cleanup pipeline. It does not call the OpenAI Image API. It cleans the rendered source page, preserves the original handwriting and diagrams, normalizes the page to printable A4, and merges the cleaned pages into the final PDF.

Cheap Mode is recommended for large PDFs and readable scans. Premium Mode is recommended for the best visual handwritten recreation.

Every generated page is then normalized to `2480x3508` pixels at `300` DPI, which matches A4 print sizing. The post-processing service:

- converts off-white and greyish background pixels to pure white
- removes tiny isolated noise spots
- preserves blue and black ink pixels as much as possible
- fits the cleaned page into a white A4 portrait canvas without stretching
- writes a final cleaned PNG before PDF merge

The final PDF is built only from these cleaned A4 PNGs, sorted by `page_no` ascending.

## API Processing Modes

`POST /jobs/create` accepts an optional mode:

```json
{
  "filename": "file.pdf",
  "fileSize": 12345,
  "pageCount": 10,
  "processingMode": "premium"
}
```

Allowed values are `premium` and `cheap`. If `processingMode` is missing, the backend defaults to `premium` for backward compatibility.

## How To Test With One PDF

1. Start `docker compose up --build`.
2. Start the web app with `npm run dev` from `apps/web`.
3. Upload one PDF under 100 pages.
4. The browser validates type, size, and page count.
5. The API creates a job and returns a presigned S3 upload URL.
6. The frontend uploads directly to S3 and starts the job.
7. The job page polls status and page-level results.
8. When completed, download the final PDF.

## Deployment Notes

- Deploy `apps/web` to Vercel with `NEXT_PUBLIC_API_URL` pointing to the hosted API.
- Deploy `apps/api` and the worker to Render, Railway, Fly, EC2, or similar.
- Use managed PostgreSQL and Redis in production.
- Use a private S3 bucket and configure CORS to allow browser `PUT` from the frontend origin.
- Never expose AWS or OpenAI secrets to the frontend.

## Cloud Deployment

### Deployment Order

1. Push the repo to GitHub.
2. Deploy the Render API first.
3. Collect the Render API URL.
4. Add `NEXT_PUBLIC_API_URL` to Vercel.
5. Deploy the Vercel frontend.
6. Collect the Vercel frontend URL.
7. Add `FRONTEND_URL` to Render.
8. Add the Vercel URL to S3 CORS.
9. Test with a 1-2 page PDF first.

### Vercel Frontend Settings

- Root Directory: `apps/web`
- Framework Preset: `Next.js`
- Install Command: `npm install`
- Build Command: `npm run build`
- Start Command: not required for normal Vercel Git deployments
- Required env: `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_MAX_PDF_PAGES`, `NEXT_PUBLIC_MAX_UPLOAD_MB`

No custom `vercel.json` is required for the frontend because Vercel can auto-detect the Next.js app when the root directory is `apps/web`.

### Render API Settings

- Root Directory: `apps/api`
- Runtime: `Python 3`
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

### Render Worker Settings

- Root Directory: `apps/api`
- Runtime: `Python 3`
- Build Command: `pip install -r requirements.txt`
- Start Command: `python -m app.workers.worker`

The worker consumes the `pdf-jobs` queue by default. Keep `RQ_QUEUE_NAME=pdf-jobs` in both API and worker environments.

### Free MVP Combined Render Service

Use this only if you want one Render Web Service running both API and worker for a free MVP test:

```bash
sh -c "rq worker pdf-jobs --url \"$REDIS_URL\" & uvicorn app.main:app --host 0.0.0.0 --port $PORT"
```

For production, prefer a separate API Web Service and Background Worker.

### Cloud Services

- Database: Supabase Postgres transaction pooler via `DATABASE_URL`.
- Queue: Upstash Redis TLS URL via `REDIS_URL`, using `rediss://default:PASSWORD@HOST.upstash.io:6379`.
- Storage: AWS S3 private bucket, such as `handwritten-pdf-recreator-prod` in `ap-south-1`.
- OpenAI: set `OPENAI_API_KEY` only in Render environment variables.

See [docs/CLOUD_ENV_TEMPLATE.md](docs/CLOUD_ENV_TEMPLATE.md) for the full cloud env checklist and notes.

## Complete In This MVP

- Single PDF upload flow
- Client and backend metadata validation
- S3 presigned upload/download URLs
- PostgreSQL job and page records
- RQ worker pipeline
- PyMuPDF page rendering at 200 DPI
- OpenAI Image API wrapper with centralized prompt
- Printable image cleanup and A4 normalization
- Final PDF merge from cleaned PNGs
- Status, failed pages, page ledger, and download UI

## Placeholders

- Page retry endpoint returns a placeholder response and does not enqueue page-specific retry work yet.
- There is no authentication or per-user ownership.
- There is no payment or quota system.
- There is no manual visual review screen before final PDF generation.

## Known MVP Limitations

- Maximum 100 pages per job.
- One PDF per job.
- Sequential page processing by default.
- The image model can occasionally alter text, labels, spelling, or diagram details.
- Page preview and retry should be added before serious final use.
- No authentication in MVP.
- No payments in MVP.
