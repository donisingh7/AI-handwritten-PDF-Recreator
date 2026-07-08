export const config = {
  apiUrl: process.env.NEXT_PUBLIC_API_URL || "",
  maxPdfPages: Number(process.env.NEXT_PUBLIC_MAX_PDF_PAGES || 100),
  maxUploadMb: Number(process.env.NEXT_PUBLIC_MAX_UPLOAD_MB || 200)
};

export const maxUploadBytes = config.maxUploadMb * 1024 * 1024;
