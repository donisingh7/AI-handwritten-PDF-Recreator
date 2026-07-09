# AWS Lightsail No-Docker Deployment

This guide deploys the FastAPI API and RQ worker on one Ubuntu AWS Lightsail server without Docker. The frontend remains on Vercel. Supabase Postgres, Upstash Redis, AWS S3, and OpenAI remain external services.

## Architecture

```text
Vercel frontend
  -> Nginx on AWS Lightsail
      -> FastAPI API on 127.0.0.1:8000
      -> RQ worker as a separate systemd service
  -> Supabase Postgres
  -> Upstash Redis queue pdf-jobs
  -> AWS S3
  -> OpenAI only for Premium Mode
```

Use at least a 2 GB Lightsail instance. Use 4 GB or more for larger Cheap Mode PDFs because OpenCV/Pillow cleanup can be memory-heavy even after page-by-page optimization.

## 1. Create the Lightsail Instance

1. Open AWS Lightsail.
2. Create an Ubuntu instance.
3. Choose a region close to your users and S3 bucket where possible.
4. Choose instance size:
   - Minimum: 2 GB RAM
   - Recommended: 4 GB RAM for larger Cheap Mode PDFs
5. Create or attach an SSH key.
6. Create the instance.

## 2. Open Firewall Ports

In the Lightsail instance Networking tab, allow:

```text
22  SSH
80  HTTP
443 HTTPS
```

Restrict SSH to your own IP if possible. HTTP and HTTPS should remain public for the API domain.

## 3. SSH Into the Server

```bash
ssh -i /path/to/lightsail-key.pem ubuntu@YOUR_LIGHTSAIL_PUBLIC_IP
```

Update the server and install system packages:

```bash
sudo apt update
sudo apt install -y git nginx python3 python3-venv python3-pip build-essential
sudo apt install -y libgl1 libglib2.0-0
sudo apt install -y certbot python3-certbot-nginx
```

`libgl1` and `libglib2.0-0` are required by OpenCV headless builds on many Ubuntu systems.

## 4. Clone the Repository

```bash
cd /home/ubuntu
git clone https://github.com/donisingh7/AI-handwritten-PDF-Recreator.git
cd AI-handwritten-PDF-Recreator/apps/api
```

## 5. Create the Python Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

Create the local temp directory used by rendering and cleanup:

```bash
sudo mkdir -p /tmp/handpdf
sudo chown -R ubuntu:ubuntu /tmp/handpdf
```

## 6. Create `/etc/handpdf.env`

Create the production environment file on the server:

```bash
sudo nano /etc/handpdf.env
```

Use `apps/api/.env.example` as the shape. Fill real values only on the server. Do not commit real secrets.

```env
APP_ENV=production
API_BASE_URL=https://api.yourdomain.com
FRONTEND_URL=https://your-vercel-app.vercel.app
CORS_ORIGINS=https://your-vercel-app.vercel.app

DATABASE_URL=
REDIS_URL=
RQ_QUEUE_NAME=pdf-jobs

AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=ap-south-1
S3_BUCKET=
S3_ENDPOINT_URL=
SIGNED_URL_EXPIRY_SECONDS=900

OPENAI_API_KEY=
OPENAI_COST_MODE=fast
OPENAI_IMAGE_MODEL=gpt-image-2
OPENAI_MINI_IMAGE_MODEL=
OPENAI_IMAGE_SIZE=1024x1536
OPENAI_IMAGE_QUALITY=high
OPENAI_IMAGE_FORMAT=png
OPENAI_OUTPUT_COMPRESSION=65
OPENAI_REQUEST_TIMEOUT_SECONDS=180
OPENAI_SOURCE_MAX_WIDTH_PX=768
OPENAI_SOURCE_MAX_HEIGHT_PX=1088

FINAL_A4_WIDTH_PX=2480
FINAL_A4_HEIGHT_PX=3508
FINAL_PRINT_DPI=300
PDF_RENDER_DPI=200

MAX_PDF_PAGES=100
MAX_UPLOAD_MB=200
TEMP_DIR=/tmp/handpdf
WORKER_CONCURRENCY=1
PAGE_PROCESSING_CONCURRENCY=1
MAX_PAGE_RETRIES=2
DEFAULT_PROCESSING_MODE=premium
JOB_AUTO_RETRY_LIMIT=3
JOB_STALE_SECONDS=900

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

REPLICATE_API_TOKEN=
REPLICATE_QWEN_IMAGE_EDIT_MODEL=qwen/qwen-image-edit
FAL_API_KEY=
FAL_KEY=
FAL_FLUX_KONTEXT_MODEL=fal-ai/flux-pro/kontext
HF_TOKEN=
HF_QWEN_IMAGE_EDIT_MODEL=Qwen/Qwen-Image-Edit
NVIDIA_API_KEY=
NVIDIA_BASE_URL=
NVIDIA_IMAGE_MODEL=
```

Protect the env file:

```bash
sudo chown root:root /etc/handpdf.env
sudo chmod 600 /etc/handpdf.env
```

Cheap Mode does not require `OPENAI_API_KEY` or any other AI provider token. Premium Mode defaults to OpenAI GPT Image 2 and requires `OPENAI_API_KEY`; optional provider tokens only enable experimental selector options.

## 7. Install systemd Services

From the repo root:

```bash
cd /home/ubuntu/AI-handwritten-PDF-Recreator
sudo cp deploy/systemd/handpdf-api.service.example /etc/systemd/system/handpdf-api.service
sudo cp deploy/systemd/handpdf-worker.service.example /etc/systemd/system/handpdf-worker.service
sudo systemctl daemon-reload
sudo systemctl enable handpdf-api
sudo systemctl enable handpdf-worker
sudo systemctl start handpdf-api
sudo systemctl start handpdf-worker
```

Check service status:

```bash
sudo systemctl status handpdf-api --no-pager
sudo systemctl status handpdf-worker --no-pager
```

Check logs:

```bash
sudo journalctl -u handpdf-api -f
sudo journalctl -u handpdf-worker -f
```

The worker logs should mention the `pdf-jobs` queue.

## 8. Verify the Local API

On the Lightsail server:

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"ok"}
```

## 9. Configure Nginx

Copy the Nginx config template:

```bash
cd /home/ubuntu/AI-handwritten-PDF-Recreator
sudo cp deploy/nginx/handpdf-api.conf.example /etc/nginx/sites-available/handpdf-api
sudo nano /etc/nginx/sites-available/handpdf-api
```

Change:

```nginx
server_name api.yourdomain.com;
```

Enable the site and test Nginx:

```bash
sudo ln -sf /etc/nginx/sites-available/handpdf-api /etc/nginx/sites-enabled/handpdf-api
sudo nginx -t
sudo systemctl reload nginx
```

If the default Nginx site conflicts, remove it:

```bash
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

Verify over HTTP:

```bash
curl http://api.yourdomain.com/health
```

## 10. Add SSL With Certbot

Point your DNS `api.yourdomain.com` A record to the Lightsail public IP first.

Then run:

```bash
sudo certbot --nginx -d api.yourdomain.com
```

Verify HTTPS:

```bash
curl https://api.yourdomain.com/health
```

Certbot installs renewal timers automatically on common Ubuntu setups. You can test renewal with:

```bash
sudo certbot renew --dry-run
```

## 11. Update Vercel

In the Vercel project settings, set:

```env
NEXT_PUBLIC_API_URL=https://api.yourdomain.com
```

Redeploy the Vercel frontend.

Also make sure `/etc/handpdf.env` on the Lightsail server has:

```env
FRONTEND_URL=https://your-vercel-app.vercel.app
CORS_ORIGINS=https://your-vercel-app.vercel.app
```

Restart API after changing CORS env:

```bash
sudo systemctl restart handpdf-api
```

## 12. Production Tests

Run the API health checks:

```bash
curl http://127.0.0.1:8000/health
curl https://api.yourdomain.com/health
```

Watch logs in two SSH terminals:

```bash
sudo journalctl -u handpdf-api -f
sudo journalctl -u handpdf-worker -f
```

Then test from the Vercel frontend:

1. Cheap Mode 1-page PDF
2. Premium Mode 1-page PDF
3. Cheap Mode 5-page PDF
4. Cheap Mode 20-page PDF
5. Cheap Mode 50-page PDF

For Cheap Mode logs, expect:

```text
Cheap mode: OpenCV/Pillow cleanup only. OpenAI skipped.
cleanup preset=strong_print
Cheap mode processing page X/Y
Cleaned temp files for page X
```

For Premium Mode logs, expect OpenAI recreation logs. Premium Mode should be tested only when `OPENAI_API_KEY` is configured.

## 13. Update / Deploy New Code

Use this flow after pushing new commits:

```bash
cd /home/ubuntu/AI-handwritten-PDF-Recreator
git pull
cd apps/api
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart handpdf-api
sudo systemctl restart handpdf-worker
```

Check status:

```bash
sudo systemctl status handpdf-api --no-pager
sudo systemctl status handpdf-worker --no-pager
```

## Troubleshooting

### API service not starting

Check:

```bash
sudo systemctl status handpdf-api --no-pager
sudo journalctl -u handpdf-api -n 100 --no-pager
```

Common causes:

- Wrong `WorkingDirectory`
- Missing `.venv`
- Missing `/etc/handpdf.env`
- Invalid `DATABASE_URL`
- Import error from missing packages

### Worker service not starting

Check:

```bash
sudo systemctl status handpdf-worker --no-pager
sudo journalctl -u handpdf-worker -n 100 --no-pager
```

Common causes:

- `REDIS_URL` missing or invalid
- `RQ_QUEUE_NAME` mismatch
- Missing Python packages
- S3 env vars missing
- Low memory during Cheap Mode cleanup

### Module import error

Reinstall dependencies:

```bash
cd /home/ubuntu/AI-handwritten-PDF-Recreator/apps/api
source .venv/bin/activate
pip install -r requirements.txt
python -m compileall app
```

### Missing env vars

Confirm the file exists and is readable by systemd:

```bash
sudo ls -l /etc/handpdf.env
sudo systemctl restart handpdf-api
sudo systemctl restart handpdf-worker
```

Do not print secret values in logs or screenshots.

### Redis queue mismatch

API and worker must both use:

```env
RQ_QUEUE_NAME=pdf-jobs
```

If the API enqueues to one queue and the worker listens to another, jobs will stay queued forever.

### S3 permission issue

Symptoms:

- Upload URL succeeds but worker cannot download original PDF
- Worker cannot upload generated pages
- Final PDF key is missing

Check the IAM user permissions for the configured bucket and region. Confirm `AWS_REGION` and `S3_BUCKET` match the real bucket.

### Supabase `DATABASE_URL` password encoding issue

If the Supabase password contains special characters like `@`, `#`, `%`, `/`, or `:`, URL-encode the password inside `DATABASE_URL`. For example, `@` becomes `%40`.

### Nginx 502

Check whether FastAPI is running:

```bash
curl http://127.0.0.1:8000/health
sudo journalctl -u handpdf-api -n 100 --no-pager
```

Then test and reload Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

### SSL or DNS issue

Check that `api.yourdomain.com` resolves to the Lightsail public IP:

```bash
dig api.yourdomain.com
```

Then rerun:

```bash
sudo certbot --nginx -d api.yourdomain.com
```

### Vercel CORS issue

Make sure the exact Vercel URL is in `/etc/handpdf.env`:

```env
FRONTEND_URL=https://your-vercel-app.vercel.app
CORS_ORIGINS=https://your-vercel-app.vercel.app
```

Restart the API:

```bash
sudo systemctl restart handpdf-api
```

### Cheap Mode still crashing due to low RAM

Use a 4 GB or larger Lightsail instance for large PDFs. You can also lower:

```env
CHEAP_MODE_RENDER_DPI=120
CHEAP_MODE_CLEANUP_MAX_WIDTH=1240
CHEAP_MODE_CLEANUP_MAX_HEIGHT=1754
```

Restart the worker after changing these values:

```bash
sudo systemctl restart handpdf-worker
```

### Restart services

```bash
sudo systemctl restart handpdf-api
sudo systemctl restart handpdf-worker
```

## References

- AWS Lightsail firewall rules: https://docs.aws.amazon.com/lightsail/latest/userguide/understanding-firewall-and-port-mappings-in-amazon-lightsail.html
- Nginx proxy module: https://nginx.org/en/docs/http/ngx_http_proxy_module.html
- Certbot Nginx usage: https://eff-certbot.readthedocs.io/en/latest/using.html#nginx
