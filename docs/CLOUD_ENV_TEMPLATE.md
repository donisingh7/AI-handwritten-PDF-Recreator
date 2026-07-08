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
OPENAI_IMAGE_SIZE=1024x1536
OPENAI_IMAGE_QUALITY=high
OPENAI_IMAGE_FORMAT=png

FINAL_A4_WIDTH_PX=2480
FINAL_A4_HEIGHT_PX=3508
FINAL_PRINT_DPI=300

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
