# Cloud Environment Template

Use these values in the Vercel and Render dashboards. Do not commit real secrets.

## A. Vercel Frontend Env

```env
NEXT_PUBLIC_API_URL=
NEXT_PUBLIC_MAX_PDF_PAGES=100
NEXT_PUBLIC_MAX_UPLOAD_MB=200
```

Set `NEXT_PUBLIC_API_URL` to the deployed Render API URL, for example:

```env
NEXT_PUBLIC_API_URL=https://your-render-api-url.onrender.com
```

## B. Render Backend / Worker Env

```env
APP_ENV=production
API_BASE_URL=
FRONTEND_URL=

OPENAI_API_KEY=
OPENAI_IMAGE_MODEL=gpt-image-2
OPENAI_MINI_IMAGE_MODEL=
OPENAI_IMAGE_SIZE=1024x1536
OPENAI_IMAGE_QUALITY=high
OPENAI_IMAGE_FORMAT=png

DEFAULT_PROCESSING_MODE=premium

FINAL_A4_WIDTH_PX=2480
FINAL_A4_HEIGHT_PX=3508
FINAL_PRINT_DPI=300
CHEAP_MODE_RENDER_DPI=150
CHEAP_MODE_CLEANUP_MAX_WIDTH=1654
CHEAP_MODE_CLEANUP_MAX_HEIGHT=2339
CHEAP_MODE_ENABLE_ADVANCED_CLEANUP=true
CHEAP_CLEANUP_PRESET=strong_print
CHEAP_BACKGROUND_STRENGTH=0.85
CHEAP_CONTRAST_STRENGTH=1.25
CHEAP_DESPECKLE_STRENGTH=medium
CHEAP_REMOVE_LIGHT_LINES=true
CHEAP_INK_DARKEN=true

REPLICATE_PROVIDER_ENABLED=false
REPLICATE_API_TOKEN=
REPLICATE_QWEN_IMAGE_EDIT_MODEL=qwen/qwen-image-edit
REPLICATE_MAX_RETRIES=8
REPLICATE_RATE_LIMIT_DELAY_SECONDS=15
REPLICATE_MIN_SECONDS_BETWEEN_PREDICTIONS=15
REPLICATE_PREDICTION_TIMEOUT_SECONDS=300
REPLICATE_QUALITY_PRESET=balanced
REPLICATE_SOURCE_MAX_WIDTH=1240
REPLICATE_SOURCE_MAX_HEIGHT=1754
REPLICATE_OUTPUT_FORMAT=png
REPLICATE_OUTPUT_QUALITY=95
REPLICATE_GO_FAST=false
REPLICATE_NUM_INFERENCE_STEPS=50
REPLICATE_GUIDANCE=4
FAL_PROVIDER_ENABLED=false
FAL_KEY=
FAL_FLUX_KONTEXT_MODEL=fal-ai/flux-pro/kontext
HF_PROVIDER_ENABLED=false
HF_TOKEN=
HF_QWEN_IMAGE_EDIT_MODEL=Qwen/Qwen-Image-Edit

AWS_REGION=ap-south-1
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
S3_BUCKET=handwritten-pdf-recreator-prod

DATABASE_URL=
REDIS_URL=
RQ_QUEUE_NAME=pdf-jobs

MAX_PDF_PAGES=100
MAX_UPLOAD_MB=200
SIGNED_URL_EXPIRY_SECONDS=900

TEMP_DIR=/tmp/handpdf
WORKER_CONCURRENCY=1
PAGE_PROCESSING_CONCURRENCY=1
MAX_PAGE_RETRIES=2
```

Cheap Mode does not require `OPENAI_API_KEY` or any provider token because it uses local OpenCV/Pillow cleanup only. It is memory-optimized for readable scans by rendering and cleaning one page at a time. Premium Mode defaults to OpenAI GPT Image 2 and requires `OPENAI_API_KEY`; Replicate, fal.ai, and Hugging Face require their `*_PROVIDER_ENABLED=true` flag plus their token before appearing as enabled selector options.

For Replicate accounts with low burst limits, keep `REPLICATE_MIN_SECONDS_BETWEEN_PREDICTIONS=15`. `REPLICATE_QUALITY_PRESET=balanced` is recommended for production testing; `high` and `print` are slower and may cost more.

`CHEAP_CLEANUP_PRESET=strong_print` is the recommended default for printable output. Use `light` for already-clean scans and `high_contrast` for dim grey scans where losing faint marks is acceptable.

## C. Supabase Migration

Run this once before deploying the processing-mode release:

```sql
ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS processing_mode VARCHAR(20) NOT NULL DEFAULT 'premium';

ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS ai_provider TEXT;

ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS ai_model TEXT;

ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS model_option_id TEXT;

ALTER TABLE jobs
ADD COLUMN IF NOT EXISTS cleanup_preset TEXT;

UPDATE jobs
SET processing_mode = 'premium'
WHERE processing_mode IS NULL;

DO $$
BEGIN
  ALTER TABLE jobs
  ADD CONSTRAINT jobs_processing_mode_check
  CHECK (processing_mode IN ('premium', 'cheap'));
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;
```

The backend also performs a best-effort additive column check at startup, but running the Supabase migration explicitly is the safest production path.

## Supabase Password Encoding

If the Supabase database password contains special characters like `@`, `#`, `%`, `/`, or `:`, the `DATABASE_URL` password must be URL-encoded. For example, `@` becomes `%40`.

Do not include any real password in repository files.

## Upstash Redis URL

For RQ, use the TLS Redis URL format:

```env
REDIS_URL=rediss://default:PASSWORD@HOST.upstash.io:6379
```

Do not use `UPSTASH_REDIS_REST_URL` as `REDIS_URL`. RQ needs a Redis protocol URL, not the REST endpoint.

## S3 CORS

After Vercel deploy, add the Vercel frontend URL to the S3 bucket CORS `AllowedOrigins`.

Keep `http://localhost:3000` for local development.

Example CORS shape:

```json
[
  {
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["GET", "PUT", "HEAD"],
    "AllowedOrigins": [
      "http://localhost:3000",
      "https://your-vercel-app.vercel.app"
    ],
    "ExposeHeaders": ["ETag"]
  }
]
```
