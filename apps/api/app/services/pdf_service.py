from pathlib import Path

import fitz


class PDFValidationError(ValueError):
    pass


class PDFService:
    def validate_pdf(self, pdf_path: Path, max_pages: int) -> int:
        if pdf_path.suffix.lower() != ".pdf":
            raise PDFValidationError("Uploaded file must have a .pdf extension.")
        try:
            with fitz.open(pdf_path) as doc:
                page_count = doc.page_count
        except Exception as exc:
            raise PDFValidationError("Uploaded file is not a readable PDF.") from exc
        if page_count < 1:
            raise PDFValidationError("Uploaded PDF must contain at least one page.")
        if page_count > max_pages:
            raise PDFValidationError(f"Uploaded PDF has {page_count} pages; the limit is {max_pages}.")
        return page_count

    def render_pages_to_png(self, pdf_path: Path, output_dir: Path, dpi: int, max_pages: int) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        page_count = self.validate_pdf(pdf_path, max_pages)
        rendered_paths: list[Path] = []
        matrix = fitz.Matrix(dpi / 72, dpi / 72)
        with fitz.open(pdf_path) as doc:
            for index in range(page_count):
                page = doc.load_page(index)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                page_no = index + 1
                output_path = output_dir / f"page_{page_no:03d}.png"
                pixmap.save(str(output_path))
                rendered_paths.append(output_path)
        return rendered_paths
