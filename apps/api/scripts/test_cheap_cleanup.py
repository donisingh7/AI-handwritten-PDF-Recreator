from pathlib import Path
import sys
import tempfile

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.services.cheap_cleanup_service import CheapCleanupService


def create_sample_scan(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1200, 1700), (232, 232, 226))
    draw = ImageDraw.Draw(image)
    for y in range(180, 1550, 70):
        draw.line((110, y, 1090, y), fill=(205, 215, 225), width=2)
    draw.line((170, 130, 170, 1580), fill=(238, 170, 170), width=3)
    draw.text((220, 250), "Cheap cleanup test page", fill=(25, 48, 120))
    draw.text((220, 350), "Preserve handwriting-like dark ink", fill=(20, 20, 20))
    draw.rectangle((210, 470, 720, 800), outline=(35, 35, 35), width=5)
    draw.ellipse((820, 480, 1010, 670), outline=(20, 75, 150), width=5)
    image.save(path, format="PNG")


def main() -> int:
    settings = get_settings()
    base_dir = Path(tempfile.gettempdir()) / "handpdf-cheap-cleanup-test"
    source_path = Path(sys.argv[1]) if len(sys.argv) > 1 else base_dir / "sample_scan.png"
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else base_dir / "output.png"

    if len(sys.argv) <= 1:
        create_sample_scan(source_path)

    service = CheapCleanupService(
        cleanup_max_width=settings.cheap_mode_cleanup_max_width,
        cleanup_max_height=settings.cheap_mode_cleanup_max_height,
        enable_advanced_cleanup=settings.cheap_mode_enable_advanced_cleanup,
    )
    strategy = service.clean_page_to_a4(
        source_path,
        output_path,
        settings.final_a4_width_px,
        settings.final_a4_height_px,
    )
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("cheap cleanup test did not create an output PNG")

    print(f"cheap cleanup ok: {output_path} strategy={strategy}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
