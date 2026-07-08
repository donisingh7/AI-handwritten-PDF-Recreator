import { UploadPanel } from "@/components/UploadPanel";

export default function HomePage() {
  return (
    <div className="workspace">
      <section className="panel upload-panel">
        <p className="eyebrow">Printable A4 pipeline</p>
        <h1 className="title">AI Handwritten PDF Recreator</h1>
        <p className="description">
          Upload one scanned practical or notebook PDF and recreate it as a clean white A4 handwritten-style PDF with preserved page order.
        </p>
        <UploadPanel />
      </section>

      <aside className="panel paper-stage" aria-label="Printable page preview">
        <div className="paper-sheet">
          <span className="paper-line black one" />
          <span className="paper-line two" />
          <span className="paper-line three" />
          <span className="paper-line black four" />
          <span className="paper-line five" />
          <span className="paper-line six" />
          <span className="diagram-box" />
        </div>
      </aside>
    </div>
  );
}
