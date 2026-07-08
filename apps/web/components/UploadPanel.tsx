"use client";

import { ChangeEvent, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { PDFDocument } from "pdf-lib";
import { AlertTriangle, CheckCircle2, FileText, Loader2, ScanLine, Sparkles, UploadCloud, type LucideIcon } from "lucide-react";
import { createJob, ProcessingMode, startJob, uploadPdf } from "@/lib/api";
import { config, maxUploadBytes } from "@/lib/config";

type UploadState = "idle" | "validating" | "ready" | "creating" | "uploading" | "starting";

const modeOptions: Array<{
  mode: ProcessingMode;
  title: string;
  subtitle: string;
  description: string;
  badge: string;
  button: string;
  cost: string;
  icon: LucideIcon;
}> = [
  {
    mode: "premium",
    title: "Premium Mode",
    subtitle: "Best quality handwritten recreation",
    description: "Uses AI image recreation to rewrite pages as clean handwritten A4 sheets.",
    badge: "Higher cost",
    button: "Use Premium",
    cost: "Higher cost because every page is recreated with AI image generation.",
    icon: Sparkles
  },
  {
    mode: "cheap",
    title: "Cheap Mode",
    subtitle: "Low-cost printable cleanup",
    description: "Uses image cleanup to make scanned pages white, clean, and printable while preserving original handwriting.",
    badge: "Low cost",
    button: "Use Cheap",
    cost: "Low cost because pages are cleaned locally without AI image generation.",
    icon: ScanLine
  }
];

export function UploadPanel() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [pageCount, setPageCount] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [state, setState] = useState<UploadState>("idle");
  const [selectedMode, setSelectedMode] = useState<ProcessingMode | null>(null);

  const selectedModeOption = modeOptions.find((option) => option.mode === selectedMode) || null;

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
    if (!file || !pageCount || !selectedMode) return;
    setError(null);
    try {
      setState("creating");
      const job = await createJob(file.name, file.size, pageCount, selectedMode);
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
      <div className="mode-grid" aria-label="Processing mode">
        {modeOptions.map((option) => {
          const Icon = option.icon;
          const isSelected = option.mode === selectedMode;
          return (
            <article className={`mode-card ${isSelected ? "selected" : ""}`} key={option.mode}>
              <div className="mode-card-header">
                <Icon size={22} />
                <span className="mode-badge">{option.badge}</span>
              </div>
              <h2>{option.title}</h2>
              <strong>{option.subtitle}</strong>
              <p>{option.description}</p>
              <p className="mode-cost">{option.cost}</p>
              <button className={isSelected ? "primary-button" : "secondary-button"} type="button" onClick={() => setSelectedMode(option.mode)} disabled={isBusy}>
                {isSelected ? <CheckCircle2 size={17} /> : <FileText size={17} />}
                {isSelected ? "Selected" : option.button}
              </button>
            </article>
          );
        })}
      </div>

      {selectedModeOption && (
        <div className="selected-mode">
          <span>Selected mode</span>
          <strong>{selectedModeOption.title}</strong>
          <p>{selectedModeOption.subtitle}</p>
        </div>
      )}

      {selectedMode && (
        <>
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
        <button className="primary-button" type="button" disabled={!file || !pageCount || !selectedMode || isBusy} onClick={handleStart}>
          {isBusy ? <Loader2 size={18} className="animate-spin" /> : <FileText size={18} />}
          {actionLabel}
        </button>
      </div>
        </>
      )}
    </div>
  );
}
