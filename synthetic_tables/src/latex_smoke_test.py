"""Run a focused LaTeX PDF smoke test against one generated sample."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from config import build_default_config
from renderers.pdf_renderer import PDFRenderer


def parse_args() -> argparse.Namespace:
    """Parse smoke-test arguments."""

    config = build_default_config()
    default_source = config.paths.rendered_latex_dir / "base_table_003__v02.tex"
    parser = argparse.ArgumentParser(
        description="Compile one generated LaTeX sample with native TeX first, then emit a forced fallback PDF for comparison.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=default_source,
        help=f"Path to the generated .tex file to inspect. Default: {default_source}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory where the diagnostic bundle will be written. Defaults to data/rendered/diagnostics/<stem>/",
    )
    parser.add_argument(
        "--latexmk-path",
        type=Path,
        help="Explicit latexmk executable path. Sets SYNTHETIC_TABLES_LATEXMK for this run.",
    )
    parser.add_argument(
        "--pdflatex-path",
        type=Path,
        help="Explicit pdflatex executable path. Sets SYNTHETIC_TABLES_PDFLATEX for this run.",
    )
    parser.add_argument(
        "--tectonic-path",
        type=Path,
        help="Explicit tectonic executable path. Sets SYNTHETIC_TABLES_TECTONIC for this run.",
    )
    return parser.parse_args()


def main() -> None:
    """Run the smoke test and print the comparison artifacts."""

    args = parse_args()
    config = build_default_config()
    source_path = args.source.resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"LaTeX sample not found: {source_path}")

    output_dir = args.output_dir or (config.paths.rendered_dir / "diagnostics" / source_path.stem)
    output_dir = output_dir.resolve()

    if args.latexmk_path:
        os.environ["SYNTHETIC_TABLES_LATEXMK"] = str(args.latexmk_path.resolve())
    if args.pdflatex_path:
        os.environ["SYNTHETIC_TABLES_PDFLATEX"] = str(args.pdflatex_path.resolve())
    if args.tectonic_path:
        os.environ["SYNTHETIC_TABLES_TECTONIC"] = str(args.tectonic_path.resolve())

    renderer = PDFRenderer()
    engine_report = renderer.latex_engine_report()
    bundle = renderer.create_latex_diagnostic_bundle(source_path=source_path, output_dir=output_dir)

    print("LaTeX smoke test completed.")
    print(f"- source: {bundle.source_path}")
    print(f"- source_copy: {bundle.source_copy_path}")
    available = engine_report["available_engines"]
    if available:
        print("- available_engines:")
        for candidate in available:
            print(f"  - {candidate['engine']}: {candidate['path']}")
    else:
        print("- available_engines: none")
        print(f"- guidance: {engine_report['guidance']}")
    print(f"- native_pdf: {bundle.native_pdf_path or 'not produced'}")
    print(f"- safe_preview_pdf: {bundle.safe_preview_pdf_path or 'not produced'}")
    print(f"- fallback_pdf: {bundle.fallback_pdf_path} ({bundle.fallback_renderer})")
    print(f"- diagnostics_json: {bundle.report_path}")
    print("- next_check: compare the native PDF against TexViewer first, then inspect the fallback PDF and log summaries if they differ.")


if __name__ == "__main__":
    main()
