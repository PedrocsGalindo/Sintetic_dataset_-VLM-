"""Render one HTML file to PDF and optionally PNG for fast HTML-only debugging."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from renderers.pdf_renderer import PDFRenderer
from renderers.pdf_to_image import PDFToImageConverter


def parse_args() -> argparse.Namespace:
    """Build the CLI for rendering a single HTML file."""

    parser = argparse.ArgumentParser(
        description="Render a single HTML file to PDF and optionally PNG for debugging.",
    )
    parser.add_argument(
        "html_path",
        type=Path,
        help="Path to the input HTML file.",
    )
    parser.add_argument(
        "--pdf-path",
        type=Path,
        help="Optional output PDF path. Defaults to data/debug/html_only/<stem>.pdf",
    )
    parser.add_argument(
        "--png-dir",
        type=Path,
        help="Optional directory for rendered page PNGs.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=150,
        help="PNG DPI when --png-dir is provided. Default: 150",
    )
    return parser.parse_args()


def default_pdf_path(html_path: Path) -> Path:
    """Choose a stable default PDF output path for HTML-only experiments."""

    return REPO_ROOT / "data" / "debug" / "html_only" / f"{html_path.stem}.pdf"


def default_png_dir(html_path: Path, dpi: int) -> Path:
    """Choose a stable default PNG output directory for HTML-only experiments."""

    return REPO_ROOT / "data" / "debug" / "html_only" / f"{html_path.stem}_{dpi}dpi"


def main() -> None:
    """Render the requested HTML file and print a short summary."""

    args = parse_args()
    html_path = args.html_path.resolve()
    if not html_path.exists():
        raise FileNotFoundError(f"HTML file not found: {html_path}")

    pdf_path = (args.pdf_path or default_pdf_path(html_path)).resolve()
    renderer = PDFRenderer()
    result = renderer.render(source_path=html_path, output_path=pdf_path, source_format="html")

    print(f"html: {html_path}")
    print(f"pdf: {result.pdf_path}")
    print(f"renderer: {result.renderer}")
    print(f"pages: {result.pages}")

    if args.png_dir is not None:
        png_dir = args.png_dir.resolve()
        image_result = PDFToImageConverter().convert(
            pdf_path=result.pdf_path,
            output_dir=png_dir,
            dpi=args.dpi,
        )
        print(f"png_dir: {png_dir}")
        print(f"png_pages: {image_result.pages}")
        return

    suggested_png_dir = default_png_dir(html_path, args.dpi)
    print(f"hint: add --png-dir \"{suggested_png_dir}\" --dpi {args.dpi} to rasterize the PDF")


if __name__ == "__main__":
    main()
