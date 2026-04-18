"""PDF-to-image conversion utilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium

from utils.io import ensure_dir


@dataclass(frozen=True)
class PDFImageResult:
    """Describe one PDF-to-image conversion output."""

    pdf_path: Path
    dpi: int
    pages: int
    page_image_paths: list[Path]


class PDFToImageConverter:
    """Convert PDF pages into image files for OCR datasets."""

    def convert(self, pdf_path: Path, output_dir: Path, dpi: int) -> PDFImageResult:
        """Convert a PDF into page images at a target DPI."""

        if dpi <= 0:
            raise ValueError(f"DPI must be a positive integer: {dpi}")
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found for image conversion: {pdf_path}")

        ensure_dir(output_dir)
        page_image_paths: list[Path] = []
        document = pdfium.PdfDocument(str(pdf_path))

        try:
            scale = dpi / 72.0
            page_count = len(document)
            if page_count <= 0:
                raise ValueError(f"PDF has no pages to render: {pdf_path}")
            for page_index in range(page_count):
                page = document[page_index]
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil()
                output_path = output_dir / f"{pdf_path.stem}_page_{page_index + 1:03d}_{dpi}dpi.png"
                image.save(output_path)
                page_image_paths.append(output_path)
                page.close()
        finally:
            document.close()

        return PDFImageResult(
            pdf_path=pdf_path,
            dpi=dpi,
            pages=len(page_image_paths),
            page_image_paths=page_image_paths,
        )
