"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, Download, FileText, Loader2, RefreshCw } from "lucide-react";
import { fetchDownloadUrl, fetchJobPages, fetchJobStatus, JobStatus, PageStatus, ProcessingMode, startJob } from "@/lib/api";

const terminalStatuses = new Set(["completed", "failed", "partially_failed"]);
const stageOrder = ["created", "uploaded", "queued", "rendering_pages", "processing_pages", "merging_pdf", "completed"];

function statusLabel(status: string): string {
  return status.replaceAll("_", " ");
}

function modeLabel(mode?: ProcessingMode): string {
  return mode === "cheap" ? "Cheap Mode" : "Premium Mode";
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.max(0, seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}m ${remainingSeconds.toString().padStart(2, "0")}s`;
}

function secondsSince(value?: string): number | null {
  if (!value) return null;
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return null;
  return Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
}

function stageCopy(status: JobStatus | null, pages: PageStatus[]): { title: string; detail: string } {
  const mode = status?.processingMode || "premium";
  switch (status?.status) {
    case "created":
    case "uploaded":
      return { title: "Preparing upload", detail: "The original PDF is being prepared for background processing." };
    case "queued":
      return { title: "Waiting for worker", detail: "The job is in queue and will start as soon as the worker picks it up." };
    case "rendering_pages": {
      const renderedPages = pages.filter((page) => page.sourceImageKey || page.status === "rendered").length;
      return {
        title: renderedPages ? `Rendering PDF pages: ${renderedPages}/${status.pageCount}` : "Rendering PDF pages",
        detail: "The backend is converting each PDF page into a source image before cleanup starts."
      };
    }
    case "processing_pages": {
      const activePage = pages.find((page) => page.status === "processing")?.pageNo;
      const action = mode === "cheap" ? "Cleaning scanned handwriting locally" : "Recreating handwriting with AI";
      return {
        title: activePage ? `${action}: page ${activePage}` : action,
        detail:
          mode === "cheap"
            ? "Cheap Mode is cleaning the rendered page without using the OpenAI Image API."
            : "Premium Mode is using AI image recreation for the active page."
      };
    }
    case "merging_pdf":
      return { title: "Building final PDF", detail: "Cleaned A4 page images are being merged into the downloadable PDF." };
    case "completed":
      return { title: "Ready to download", detail: "The final printable A4 PDF has been generated." };
    case "partially_failed":
      return { title: "Some pages failed", detail: "Processing finished, but at least one page could not be completed." };
    case "failed":
      return { title: "Processing failed", detail: "The backend stopped this job because an error occurred." };
    default:
      return { title: "Loading job", detail: "Fetching the latest job status from the backend." };
  }
}

function progressPercent(status: JobStatus | null, pages: PageStatus[]): number {
  if (!status?.pageCount) return 0;
  if (terminalStatuses.has(status.status)) return status.status === "completed" ? 100 : Math.max(10, Math.round((status.completedPages / status.pageCount) * 100));
  if (status.status === "queued") return 10;
  if (status.status === "rendering_pages") {
    const renderedPages = pages.filter((page) => page.sourceImageKey || page.status === "rendered").length;
    const renderProgress = renderedPages / status.pageCount;
    return Math.min(25, Math.max(12, Math.round(12 + renderProgress * 13)));
  }
  if (status.status === "merging_pdf") return 94;
  if (status.status === "processing_pages") {
    const processingPages = pages.filter((page) => page.status === "processing").length;
    const pageProgress = (status.completedPages + processingPages * 0.5) / status.pageCount;
    return Math.min(88, Math.max(25, Math.round(25 + pageProgress * 63)));
  }
  return 5;
}

function estimateCopy(status: JobStatus | null, pages: PageStatus[], elapsedSeconds: number): string {
  if (!status) return "Waiting for status...";
  if (status.status === "completed") return "Finished";
  if (status.status === "failed" || status.status === "partially_failed") return "Stopped";
  if (status.status === "rendering_pages") {
    const renderedPages = pages.filter((page) => page.sourceImageKey || page.status === "rendered").length;
    const remainingPages = Math.max(0, status.pageCount - renderedPages);
    if (renderedPages > 0 && remainingPages > 0) {
      const averageSeconds = elapsedSeconds / renderedPages;
      return `Rendering, about ${formatDuration(Math.ceil(averageSeconds * remainingPages))}`;
    }
    return "Preparing first rendered page...";
  }
  const remainingPages = Math.max(0, status.pageCount - status.completedPages);
  if (status.status === "processing_pages" && status.completedPages > 0 && remainingPages > 0) {
    const averageSeconds = elapsedSeconds / status.completedPages;
    return `About ${formatDuration(Math.ceil(averageSeconds * remainingPages))}`;
  }
  if (status.status === "processing_pages") {
    return status.processingMode === "cheap" ? "Cleaning locally, usually faster than Premium" : "AI recreation may take a few minutes per page";
  }
  return "Calculating...";
}

export function JobProgress({ jobId }: { jobId: string }) {
  const [status, setStatus] = useState<JobStatus | null>(null);
  const [pages, setPages] = useState<PageStatus[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [visibleStartedAt] = useState(() => Date.now());
  const terminalRef = useRef(false);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const [jobStatus, pageStatuses] = await Promise.all([fetchJobStatus(jobId), fetchJobPages(jobId)]);
      terminalRef.current = terminalStatuses.has(jobStatus.status);
      setStatus(jobStatus);
      setPages(pageStatuses);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load job status.");
    } finally {
      setRefreshing(false);
    }
  }, [jobId]);

  useEffect(() => {
    const run = () => {
      if (!terminalRef.current) {
        void load();
      }
    };
    const initial = window.setTimeout(run, 0);
    const timer = window.setInterval(() => {
      run();
    }, 3000);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
    };
  }, [load]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const progress = useMemo(() => progressPercent(status, pages), [status, pages]);
  const elapsedSeconds = Math.floor((now - visibleStartedAt) / 1000);
  const currentStage = stageCopy(status, pages);
  const currentStageIndex = status ? stageOrder.indexOf(status.status) : -1;
  const estimate = estimateCopy(status, pages, elapsedSeconds);
  const backendIdleSeconds = secondsSince(status?.updatedAt);
  const staleThresholdSeconds = status?.processingMode === "premium" ? 360 : 180;
  const isPossiblyStalled = Boolean(
    status && !terminalStatuses.has(status.status) && backendIdleSeconds !== null && backendIdleSeconds > staleThresholdSeconds
  );

  async function handleDownload() {
    if (!status) return;
    try {
      setError(null);
      const { url } = await fetchDownloadUrl(status.jobId);
      window.location.href = url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not prepare the download link.");
    }
  }

  async function handleRetry() {
    if (!status) return;
    try {
      setRetrying(true);
      setError(null);
      await startJob(status.jobId);
      terminalRef.current = false;
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not retry this job.");
    } finally {
      setRetrying(false);
    }
  }

  const pillClass = status?.status === "completed" ? "status-pill done" : status?.status?.includes("failed") ? "status-pill failed" : "status-pill";

  return (
    <div className="page-shell">
      <div className="job-grid">
        <section className="panel status-panel">
          <div className="status-header">
            <div>
              <p className="eyebrow">Job ID</p>
              <h1 className="status-title">{jobId}</h1>
            </div>
            <span className={pillClass}>
              {refreshing && !status ? <Loader2 size={16} className="animate-spin" /> : <FileText size={16} />}
              {status ? statusLabel(status.status) : "loading"}
            </span>
          </div>

          {error && (
            <div className="notice" style={{ marginTop: 18 }}>
              <AlertTriangle size={18} />
              <span>{error}</span>
            </div>
          )}

          {isPossiblyStalled ? (
            <div className="notice" style={{ marginTop: 18 }}>
              <AlertTriangle size={18} />
              <span>No backend progress for {formatDuration(backendIdleSeconds ?? 0)}. The worker may have stopped; refresh once or retry after redeploy.</span>
            </div>
          ) : null}

          <div style={{ marginTop: 28 }}>
            <div className="progress-topline">
              <div>
                <strong>{currentStage.title}</strong>
                <span>{currentStage.detail}</span>
              </div>
              <span>{progress}%</span>
            </div>
            <div className="progress-shell" aria-label="Job progress">
              <div className="progress-fill" style={{ width: `${progress}%` }} />
            </div>
          </div>

          <div className="stage-track" aria-label="Processing stages">
            {stageOrder.slice(2).map((stage, index) => {
              const absoluteIndex = index + 2;
              const isActive = status?.status === stage;
              const isDone = status?.status === "completed" || (currentStageIndex >= absoluteIndex && currentStageIndex !== -1);
              return <span className={`stage-dot ${isDone ? "done" : ""} ${isActive ? "active" : ""}`} key={stage} title={statusLabel(stage)} />;
            })}
          </div>

          <div className="progress-grid" style={{ marginTop: 18 }}>
            <div className="metric">
              <span>Mode</span>
              <strong>{modeLabel(status?.processingMode)}</strong>
            </div>
            <div className="metric">
              <span>{status?.processingMode === "cheap" ? "Cleanup" : "Model"}</span>
              <strong>{status?.processingMode === "cheap" ? status?.cleanupPreset?.replaceAll("_", " ") || "-" : status?.aiModel || "-"}</strong>
            </div>
            <div className="metric">
              <span>Elapsed</span>
              <strong>{formatDuration(elapsedSeconds)}</strong>
            </div>
            <div className="metric">
              <span>Estimate</span>
              <strong>{estimate}</strong>
            </div>
            <div className="metric">
              <span>Last update</span>
              <strong>{backendIdleSeconds === null ? "-" : `${formatDuration(backendIdleSeconds)} ago`}</strong>
            </div>
          </div>

          <div className="field-grid" style={{ marginTop: 12 }}>
            <div className="metric">
              <span>Page count</span>
              <strong>{status?.pageCount ?? "-"}</strong>
            </div>
            <div className="metric">
              <span>Completed</span>
              <strong>{status?.completedPages ?? "-"}</strong>
            </div>
            <div className="metric">
              <span>Failed</span>
              <strong>{status?.failedPages.length ?? 0}</strong>
            </div>
          </div>

          {status?.failedPages.length ? (
            <div className="notice" style={{ marginTop: 18 }}>
              <AlertTriangle size={18} />
              <span>Failed pages: {status.failedPages.join(", ")}</span>
            </div>
          ) : null}

          {status?.error ? (
            <div className="notice" style={{ marginTop: 18 }}>
              <AlertTriangle size={18} />
              <span>{status.error}</span>
            </div>
          ) : null}

          <div className="action-row" style={{ marginTop: 22 }}>
            <button className="secondary-button" type="button" onClick={load} disabled={refreshing}>
              {refreshing ? <Loader2 size={17} className="animate-spin" /> : <RefreshCw size={17} />}
              Refresh
            </button>
            {status?.status === "completed" && (
              <button className="primary-button" type="button" onClick={handleDownload}>
                <Download size={18} />
                Download PDF
              </button>
            )}
            {(status?.status === "failed" || status?.status === "partially_failed") && (
              <button className="primary-button" type="button" onClick={handleRetry} disabled={retrying}>
                {retrying ? <Loader2 size={18} className="animate-spin" /> : <RefreshCw size={18} />}
                Retry Job
              </button>
            )}
            <Link className="secondary-button" href="/">
              New PDF
            </Link>
          </div>
        </section>

        <aside className="panel status-panel">
          <p className="eyebrow">Page ledger</p>
          <div className="page-list">
            {pages.length ? (
              pages.map((page) => (
                <div className={`page-chip ${page.status}`} key={page.pageNo} title={page.error || page.status}>
                  <span>{page.pageNo.toString().padStart(3, "0")}</span>
                  {page.status === "completed" ? <CheckCircle2 size={16} /> : page.status === "failed" ? <AlertTriangle size={16} /> : <FileText size={16} />}
                </div>
              ))
            ) : (
              <div className="page-chip">
                <span>Waiting</span>
                <Loader2 size={16} className="animate-spin" />
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
