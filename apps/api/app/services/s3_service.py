import json
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from app.config import Settings, get_settings


class S3Service:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = None

    @property
    def client(self):
        if self._client is None:
            if not self.settings.s3_bucket or self.settings.s3_bucket == "replace-me-private-bucket":
                raise RuntimeError("S3_BUCKET must be configured before storage operations can run.")
            self._client = boto3.client(
                "s3",
                region_name=self.settings.aws_region,
                endpoint_url=self.settings.s3_endpoint_url or None,
                aws_access_key_id=self.settings.aws_access_key_id or None,
                aws_secret_access_key=self.settings.aws_secret_access_key or None,
            )
        return self._client

    def create_presigned_upload_url(self, key: str) -> str:
        return self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.settings.s3_bucket, "Key": key, "ContentType": "application/pdf"},
            ExpiresIn=self.settings.s3_presigned_expires_seconds,
        )

    def create_presigned_download_url(self, key: str) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.settings.s3_bucket, "Key": key},
            ExpiresIn=self.settings.s3_presigned_expires_seconds,
        )

    def object_exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.settings.s3_bucket, Key=key)
            return True
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                return False
            raise

    def upload_file(self, local_path: Path, key: str, content_type: str) -> None:
        self.client.upload_file(
            str(local_path),
            self.settings.s3_bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )

    def download_file(self, key: str, local_path: Path) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.settings.s3_bucket, key, str(local_path))

    def put_json(self, key: str, payload: dict[str, Any]) -> None:
        self.client.put_object(
            Bucket=self.settings.s3_bucket,
            Key=key,
            Body=json.dumps(payload, indent=2).encode("utf-8"),
            ContentType="application/json",
        )


def page_png_key(job_id: str, page_no: int, kind: str) -> str:
    return f"jobs/{job_id}/{kind}/page_{page_no:03d}.png"


def input_pdf_key(job_id: str) -> str:
    return f"jobs/{job_id}/input/original.pdf"


def final_pdf_key(job_id: str) -> str:
    return f"jobs/{job_id}/final/output.pdf"


def manifest_key(job_id: str) -> str:
    return f"jobs/{job_id}/manifest.json"
