"use client";

import { ChangeEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { PDFDocument } from "pdf-lib";
import { AlertTriangle, CheckCircle2, FileText, Loader2, ScanLine, Sparkles, UploadCloud, type LucideIcon } from "lucide-react";
import { CleanupPreset, createJob, fetchModels, ModelOption, ProcessingMode, startJob, uploadPdf } from "@/lib/api";
import { config, maxUploadBytes } from "@/lib/config";

type UploadState = "idle" | "validating" | "ready" | "creating" | "uploading" | "starting";
type ModelState = "idle" | "loading" | "ready" | "failed";

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

const cleanupOptions: Array<{
  value: CleanupPreset;
  label: string;
  description: string;
}> = [
  {
    value: "light",
    label: "Light",
    description: "Conservative cleanup for already clear scans."
  },
  {
    value: "strong_print",
    label: "Strong Printable",
    description: "Recommended default for whiter, cleaner printable pages."
  },
  {
    value: "high_contrast",
    label: "High Contrast",
    description: "Most aggressive cleanup for dim grey scans; may lose faint marks."
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
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
  const [modelState, setModelState] = useState<ModelState>("loading");
  const [selectedModelOptionId, setSelectedModelOptionId] = useState<string>("openai:gpt-image-2");
  const [cleanupPreset, setCleanupPreset] = useState<CleanupPreset>("strong_print");

  const selectedModeOption = modeOptions.find((option) => option.mode === selectedMode) || null;
  const premiumModelOptions = useMemo(() => modelOptions.filter((option) => option.mode === "premium"), [modelOptions]);
  const selectedModelOption = premiumModelOptions.find((option) => option.id === selectedModelOptionId) || premiumModelOptions[0] || null;
  const selectedCleanupOption = cleanupOptions.find((option) => option.value === cleanupPreset) || cleanupOptions[1];

  const selectedSize = useMemo(() => {
    if (!file) return "No file";
    return `${(file.size / 1024 / 1024).toFixed(2)} MB`;
  }, [file]);

  useEffect(() => {
    let isMounted = true;
    fetchModels()
      .then((options) => {
        if (!isMounted) return;
        setModelOptions(options);
        const defaultOption = options.find((option) => option.id === "openai:gpt-image-2") || options.find((option) => option.enabled) || options[0];
        if (defaultOption) {
          setSelectedModelOptionId(defaultOption.id);
        }
        setModelState("ready");
      })
      .catch(() => {
        if (!isMounted) return;
        setModelState("failed");
      });
    return () => {
      isMounted = false;
    };
  }, []);

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
    if (selectedMode === "premium" && !selectedModelOption) {
      setError("Select a premium model before starting.");
      return;
    }
    setError(null);
    try {
      setState("creating");
      const job = await createJob(file.name, file.size, pageCount, selectedMode, {
        modelOptionId: selectedMode === "premium" ? selectedModelOption?.id : null,
        cleanupPreset: selectedMode === "cheap" ? cleanupPreset : null
      });
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
  const isPremiumModelUnavailable = selectedMode === "premium" && (!selectedModelOption || !selectedModelOption.enabled);
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

      {selectedMode === "premium" && (
        <div className="option-panel">
          <div className="option-header">
            <div>
              <span>Premium model</span>
              <strong>{selectedModelOption?.label || "Loading models"}</strong>
            </div>
            {modelState === "loading" ? <Loader2 size={18} className="animate-spin" /> : <Sparkles size={18} />}
          </div>
          <label className="select-field">
            <span>Provider / model</span>
            <select
              value={selectedModelOptionId}
              onChange={(event) => setSelectedModelOptionId(event.target.value)}
              disabled={isBusy || modelState === "loading" || !premiumModelOptions.length}
            >
              {premiumModelOptions.map((option) => (
                <option disabled={!option.enabled} key={option.id} value={option.id}>
                  {option.label}
                  {option.enabled ? "" : " (not configured)"}
                </option>
              ))}
            </select>
          </label>
          <p className="option-copy">
            {selectedModelOption
              ? selectedModelOption.description
              : modelState === "failed"
                ? "Could not load model options from the backend."
                : "Loading available premium models..."}
          </p>
          {selectedModelOption?.disabledReason ? <p className="option-warning">{selectedModelOption.disabledReason}</p> : null}
          <p className="option-warning">Different models may change text accuracy and output style. Test 1 page first.</p>
        </div>
      )}

      {selectedMode === "cheap" && (
        <div className="option-panel">
          <div className="option-header">
            <div>
              <span>Cheap cleanup</span>
              <strong>{selectedCleanupOption.label}</strong>
            </div>
            <ScanLine size={18} />
          </div>
          <label className="select-field">
            <span>Cleanup level</span>
            <select value={cleanupPreset} onChange={(event) => setCleanupPreset(event.target.value as CleanupPreset)} disabled={isBusy}>
              {cleanupOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <p className="option-copy">{selectedCleanupOption.description}</p>
          <p className="option-warning">Cheap mode cleans existing handwriting. It does not recreate new handwriting.</p>
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
        <button className="primary-button" type="button" disabled={!file || !pageCount || !selectedMode || isBusy || isPremiumModelUnavailable} onClick={handleStart}>
          {isBusy ? <Loader2 size={18} className="animate-spin" /> : <FileText size={18} />}
          {actionLabel}
        </button>
      </div>
        </>
      )}
    </div>
  );
}
