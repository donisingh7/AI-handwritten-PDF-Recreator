"use client";

import { ChangeEvent, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { PDFDocument } from "pdf-lib";
import { AlertTriangle, CheckCircle2, FileText, Loader2, UploadCloud } from "lucide-react";
import { createJob, startJob, uploadPdf } from "@/lib/api";
import { config, maxUploadBytes } from "@/lib/config";

type UploadState = "idle" | "validating" | "ready" | "creating" | "uploading" | "starting";

export function UploadPanel() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [pageCount, setPageCount] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [state, setState] = useState<UploadState>("idle");

  const selectedSize = useMemo(() => {
    if (!file) return "No file";
    return `${(file.size / 1024 / 1024).toFixed(2)} MB`;
  }, [file]);

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] || null;
    setFile(null);
    setPageCount(null);
    setUploadProgress(0);
    setError(null);

    if (!selected) {
      setState("idle");
      return;
    }

    setState("validating");
    try {
      if (selected.type !== "application/pdf" && !selected.name.toLowerCase().endsWith(".pdf")) {
        throw new Error("Select a PDF file.");
      }
      if (selected.size > maxUploadBytes) {
        throw new Error(`File is larger than ${config.maxUploadMb} MB.`);
      }

      const bytes = await selected.arrayBuffer();
      const pdf = await PDFDocument.load(bytes);
      const pages = pdf.getPageCount();
      if (pages < 1) {
        throw new Error("PDF must contain at least one page.");
      }
      if (pages > config.maxPdfPages) {
        throw new Error(`PDF has ${pages} pages. The limit is ${config.maxPdfPages}.`);
      }

      setFile(selected);
      setPageCount(pages);
      setState("ready");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not validate this PDF.");
      setState("idle");
      event.target.value = "";
    }
  }

  async function handleStart() {
    if (!file || !pageCount) return;
    setError(null);
    try {
      setState("creating");
      const job = await createJob(file.name, file.size, pageCount);
      setState("uploading");
      await uploadPdf(job.uploadUrl, file, setUploadProgress);
      setState("starting");
      await startJob(job.jobId);
      router.push(`/jobs/${job.jobId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start processing.");
      setState("ready");
    }
  }

  const isBusy = ["validating", "creating", "uploading", "starting"].includes(state);
  const actionLabel =
    state === "creating" ? "Creating job" : state === "uploading" ? "Uploading PDF" : state === "starting" ? "Starting worker" : "Start Processing";

  return (
    <div className="upload-zone">
      <label className="file-input-wrap">
        <input type="file" accept="application/pdf" multiple={false} onChange={handleFileChange} disabled={isBusy} />
        <span className="file-input-content">
          <UploadCloud size={34} />
          <strong>{file ? file.name : "Choose one PDF"}</strong>
          <span>PDF only, up to {config.maxPdfPages} pages</span>
        </span>
      </label>

      <div className="field-grid">
        <div className="metric">
          <span>File</span>
          <strong>{file?.name || "Waiting"}</strong>
        </div>
        <div className="metric">
          <span>Pages</span>
          <strong>{pageCount ?? "-"}</strong>
        </div>
        <div className="metric">
          <span>Size</span>
          <strong>{selectedSize}</strong>
        </div>
      </div>

      {state === "validating" && (
        <div className="notice success">
          <Loader2 size={18} className="animate-spin" />
          <span>Reading PDF page count...</span>
        </div>
      )}

      {error && (
        <div className="notice">
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      )}

      {pageCount && !error && state === "ready" && (
        <div className="notice success">
          <CheckCircle2 size={18} />
          <span>Ready to process {pageCount} page{pageCount === 1 ? "" : "s"}.</span>
        </div>
      )}

      {state === "uploading" && (
        <div>
          <div className="progress-shell" aria-label="Upload progress">
            <div className="progress-fill" style={{ width: `${uploadProgress}%` }} />
          </div>
        </div>
      )}

      <div className="action-row">
        <button className="primary-button" type="button" disabled={!file || !pageCount || isBusy} onClick={handleStart}>
          {isBusy ? <Loader2 size={18} className="animate-spin" /> : <FileText size={18} />}
          {actionLabel}
        </button>
      </div>
    </div>
  );
}
