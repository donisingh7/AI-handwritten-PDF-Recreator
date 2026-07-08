"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { AlertTriangle, CheckCircle2, Download, FileText, Loader2, RefreshCw } from "lucide-react";
import { fetchDownloadUrl, fetchJobPages, fetchJobStatus, JobStatus, PageStatus } from "@/lib/api";

const terminalStatuses = new Set(["completed", "failed", "partially_failed"]);

function statusLabel(status: string): string {
  return status.replaceAll("_", " ");
}

export function JobProgress({ jobId }: { jobId: string }) {
  const [status, setStatus] = useState<JobStatus | null>(null);
  const [pages, setPages] = useState<PageStatus[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
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

  const progress = useMemo(() => {
    if (!status?.pageCount) return 0;
    if (status.status === "completed") return 100;
    return Math.round((status.completedPages / status.pageCount) * 100);
  }, [status]);

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

          <div style={{ marginTop: 28 }}>
            <div className="progress-shell" aria-label="Job progress">
              <div className="progress-fill" style={{ width: `${progress}%` }} />
            </div>
          </div>

          <div className="field-grid" style={{ marginTop: 18 }}>
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
