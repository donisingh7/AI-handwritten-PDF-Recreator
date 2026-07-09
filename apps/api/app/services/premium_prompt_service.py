from app.config import Settings, get_settings


class PremiumPromptService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def build_prompt(self, page_no: int, retry_attempt: int = 0) -> str:
        heading_color = self.settings.premium_heading_ink_color
        body_color = self.settings.premium_body_ink_color
        diagram_color = self.settings.premium_diagram_ink_color.replace("_", "/")
        base = [
            f"Recreate page {page_no} from the reference image as clean A4 portrait handwriting.",
            "Preserve the original page content, order, labels, equations, diagrams, and layout faithfully.",
            "Rewrite/recreate the content on plain clean unruled A4 white paper.",
            "Use a pure white background with no paper texture.",
            "Do not include ruled notebook lines, horizontal guide lines, vertical margin lines, borders, shadows, stains, scan marks, grey texture, watermarks, or extra marks.",
            f"Render all headings, section titles, subheadings, underlines, and captions in {heading_color} ink.",
            f"Render normal body writing in {body_color} ballpoint-style ink.",
            f"Render diagrams as clean hand-drawn lines in {diagram_color} ink while preserving labels and arrows.",
            "Keep a natural human handwritten look with small realistic imperfections, but keep the page clean and printable.",
            "Do not add decorations, corrections, summaries, new content, or missing content.",
        ]
        if self.settings.premium_force_plain_a4:
            base.append("The output must look like a fresh handwritten practical page on blank A4 paper, not a scan or notebook page.")
        if self.settings.premium_force_pure_white_background:
            base.append("Every non-ink background pixel should be pure white.")
        if retry_attempt > 0:
            base.extend(
                [
                    "Previous output did not satisfy the clean A4 style.",
                    "Be stricter: remove all notebook ruling, margin marks, grey paper texture, shadows, stains, and background artefacts.",
                    "Use black ink only for headings and blue ink for body writing.",
                ]
            )
        return "\n".join(base)
