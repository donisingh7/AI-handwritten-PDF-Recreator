from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


class MergeService:
    def merge_pngs_to_pdf(self, ordered_page_images: list[Path], output_pdf_path: Path) -> Path:
        if not ordered_page_images:
            raise ValueError("No generated page images were provided for PDF merge.")

        output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf = canvas.Canvas(str(output_pdf_path), pagesize=A4)
        page_width, page_height = A4

        for image_path in ordered_page_images:
            reader = ImageReader(str(image_path))
            pdf.drawImage(reader, 0, 0, width=page_width, height=page_height, preserveAspectRatio=True, mask="auto")
            pdf.showPage()

        pdf.save()
        return output_pdf_path
