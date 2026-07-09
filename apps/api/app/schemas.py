from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class JobCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    filename: str
    file_size: int = Field(alias="fileSize", gt=0)
    page_count: int = Field(alias="pageCount", gt=0)
    processing_mode: str | None = Field(default=None, alias="processingMode")


class JobCreateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(alias="jobId")
    upload_url: str = Field(alias="uploadUrl")
    s3_key: str = Field(alias="s3Key")
    processing_mode: str = Field(alias="processingMode")


class StartJobResponse(BaseModel):
    status: str


class PageStatusResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    page_no: int = Field(alias="pageNo")
    status: str
    source_image_key: str | None = Field(default=None, alias="sourceImageKey")
    generated_image_key: str | None = Field(default=None, alias="generatedImageKey")
    error: str | None = None
    retry_count: int = Field(alias="retryCount")


class JobStatusResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(alias="jobId")
    status: str
    processing_mode: str = Field(alias="processingMode")
    page_count: int = Field(alias="pageCount")
    completed_pages: int = Field(alias="completedPages")
    failed_pages: list[int] = Field(alias="failedPages")
    final_pdf_url: str | None = Field(default=None, alias="finalPdfUrl")
    error: str | None = None
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class DownloadUrlResponse(BaseModel):
    url: str


class RetryPageResponse(BaseModel):
    status: str
    message: str
