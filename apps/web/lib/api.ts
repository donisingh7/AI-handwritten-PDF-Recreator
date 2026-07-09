import { config } from "@/lib/config";

export type CreateJobResponse = {
  jobId: string;
  uploadUrl: string;
  s3Key: string;
  processingMode: ProcessingMode;
};

export type ProcessingMode = "premium" | "cheap";

export type JobStatus = {
  jobId: string;
  status: string;
  processingMode: ProcessingMode;
  pageCount: number;
  completedPages: number;
  failedPages: number[];
  finalPdfUrl: string | null;
  error: string | null;
  createdAt: string;
  updatedAt: string;
};

export type PageStatus = {
  pageNo: number;
  status: string;
  sourceImageKey: string | null;
  generatedImageKey: string | null;
  error: string | null;
  retryCount: number;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (!config.apiUrl) {
    throw new Error("NEXT_PUBLIC_API_URL is not configured. Add your Render API URL in Vercel environment variables.");
  }

  const response = await fetch(`${config.apiUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    }
  });

  if (!response.ok) {
    let message = `Request failed with ${response.status}`;
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch {
      // Keep the HTTP status message.
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

export function createJob(filename: string, fileSize: number, pageCount: number, processingMode: ProcessingMode): Promise<CreateJobResponse> {
  return request<CreateJobResponse>("/jobs/create", {
    method: "POST",
    body: JSON.stringify({ filename, fileSize, pageCount, processingMode })
  });
}

export function startJob(jobId: string): Promise<{ status: string }> {
  return request<{ status: string }>(`/jobs/${jobId}/start`, { method: "POST" });
}

export function fetchJobStatus(jobId: string): Promise<JobStatus> {
  return request<JobStatus>(`/jobs/${jobId}/status`);
}

export function fetchJobPages(jobId: string): Promise<PageStatus[]> {
  return request<PageStatus[]>(`/jobs/${jobId}/pages`);
}

export function fetchDownloadUrl(jobId: string): Promise<{ url: string }> {
  return request<{ url: string }>(`/jobs/${jobId}/download-url`);
}

export function uploadPdf(uploadUrl: string, file: File, onProgress: (progress: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", uploadUrl);
    xhr.setRequestHeader("Content-Type", "application/pdf");

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(100);
        resolve();
      } else {
        reject(new Error(`Upload failed with ${xhr.status}`));
      }
    };

    xhr.onerror = () => reject(new Error("Upload failed before S3 accepted the file."));
    xhr.send(file);
  });
}
