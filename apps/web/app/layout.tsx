import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI Handwritten PDF Recreator",
  description: "Convert scanned practical PDFs into clean printable handwritten-style A4 PDFs."
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <main className="app-shell">
          <div className="top-bar">
            <Link className="brand-mark" href="/">
              <span className="brand-dot" aria-hidden="true" />
              <span>AI Handwritten PDF Recreator</span>
            </Link>
          </div>
          {children}
        </main>
      </body>
    </html>
  );
}
