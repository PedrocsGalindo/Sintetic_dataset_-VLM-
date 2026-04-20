# synthetic_tables

> Built with Codex GPT-5.4

`synthetic_tables` is a modular Python project for generating synthetic table datasets aimed at OCR and table extraction workflows.

The purpose of this repository is to create document-like, visually varied table layouts for information extraction experiments. It generates the same structured content across different formats, styles, and rendering variables so you can test OCR pipelines and VLM-based document understanding systems under a range of layout conditions.

The project now covers the full pipeline implemented in stages:

- stage 1: project skeleton and module structure
- stage 2: synthetic base table generation plus CSV/XLSX export
- stage 3: intermediate HTML, LaTeX, and Markdown representations with sampled styles
- stage 4: PDF rendering, page-image extraction, and sample metadata
- stage 5: final integration, validation, configuration, and usability pass

## Pipeline overview

The pipeline runs end-to-end as follows:

1. Generate a synthetic schema for each table.
2. Generate coherent column values and assemble the base table in memory.
3. Export the base table to CSV and XLSX.
4. Generate styled intermediate representations in HTML, LaTeX, and Markdown.
5. Render each intermediate representation to PDF.
6. Convert each PDF into page images at one or more DPI values.
7. Persist table-level metadata in `tables.jsonl`.
8. Persist sample-level metadata in `samples.jsonl`.

This makes the same structured table appear in multiple visual variants, formats, and rasterization levels, which is useful for downstream OCR and table extraction experiments.

## Project structure

```text
synthetic_tables/
  data/
    base_tables/
      csv/
      xlsx/
      schemas/
    rendered/
      html/
      latex/
      markdown/
      pdf/
      images/
    metadata/
      tables.jsonl
      samples.jsonl
  src/
    config.py
    main.py
    generators/
      schema_generator.py
      column_generators.py
      table_generator.py
    exporters/
      csv_exporter.py
      xlsx_exporter.py
      format_exporter.py
    styles/
      style_sampler.py
      templates/
        html/
        latex/
    renderers/
      html_renderer.py
      latex_renderer.py
      markdown_renderer.py
      pdf_renderer.py
      pdf_to_image.py
    metadata/
      metadata_writer.py
    utils/
      io.py
      ids.py
      seed.py
  requirements.txt
  README.md
```

## Installation

1. Create the virtual environment inside the project:

```bash
python -m venv synthetic_tables/.venv
```

2. Install the dependencies into that `venv`:

```bash
synthetic_tables\.venv\Scripts\python.exe -m pip install -r synthetic_tables/requirements.txt
```

3. Install the Chromium runtime used by the default HTML -> PDF renderer:

```bash
synthetic_tables\.venv\Scripts\python.exe -m playwright install chromium
```

4. If you plan to render LaTeX PDFs, install a real TeX engine. On Windows, MiKTeX is the recommended setup. Make sure `latexmk.exe` or `pdflatex.exe` is available on `PATH`, or point the project at the executable explicitly with:

- `SYNTHETIC_TABLES_LATEXMK`
- `LATEXMK_PATH`
- `SYNTHETIC_TABLES_PDFLATEX`
- `PDFLATEX_PATH`
- `SYNTHETIC_TABLES_TECTONIC`
- `TECTONIC_PATH`

5. Optional: verify the `venv` is the one being used:

```bash
synthetic_tables\.venv\Scripts\python.exe -m pip list
```

## How To Run

Run the complete pipeline with defaults:

```bash
synthetic_tables\.venv\Scripts\python.exe synthetic_tables/src/main.py
```

Run the focused LaTeX smoke test against one representative generated sample:

```bash
synthetic_tables\.venv\Scripts\python.exe synthetic_tables/src/latex_smoke_test.py
```

If TexViewer is using a TeX install that is not on `PATH`, point the smoke test at that exact executable:

```bash
$env:SYNTHETIC_TABLES_LATEXMK = "C:\Path\To\latexmk.exe"
synthetic_tables\.venv\Scripts\python.exe synthetic_tables/src/latex_smoke_test.py ^
  --source synthetic_tables/data/rendered/latex/base_table_003__v02.tex
```

The smoke test writes a diagnostic bundle under `data/rendered/diagnostics/<sample_stem>/` containing:

- a copy of the generated `.tex`
- the native TeX-compiled PDF if available
- a safe-preview PDF if the creative source fails but the engine still compiles the compatibility source
- the forced fallback PDF used only for diagnostics-side comparison
- TeX log files for each attempt
- a JSON report summarizing engine discovery and likely failure causes

The forced fallback PDF is diagnostic-only. The normal LaTeX rendering path now requires a real TeX engine and does not use non-TeX PDF fallback rendering.

The default run generates:

- base schemas in `data/base_tables/schemas/`
- base CSV files in `data/base_tables/csv/`
- base XLSX files in `data/base_tables/xlsx/`
- styled HTML files in `data/rendered/html/`
- styled LaTeX files in `data/rendered/latex/`
- styled Markdown files in `data/rendered/markdown/`
- PDFs in `data/rendered/pdf/`
- page images in `data/rendered/images/`
- table metadata in `data/metadata/tables.jsonl`
- sample metadata in `data/metadata/samples.jsonl`

## Configuration

The pipeline is configurable from the command line.

### Number of base tables

```bash
synthetic_tables\.venv\Scripts\python.exe synthetic_tables/src/main.py --table-count 6
```

### Number of visual versions

This controls how many distinct style variants are generated per source format.

```bash
synthetic_tables\.venv\Scripts\python.exe synthetic_tables/src/main.py --visual-versions 3
```

### Seed

```bash
synthetic_tables\.venv\Scripts\python.exe synthetic_tables/src/main.py --seed 123
```

### Range of rows

```bash
synthetic_tables\.venv\Scripts\python.exe synthetic_tables/src/main.py --min-rows 50 --max-rows 120
```

### Range of columns

```bash
synthetic_tables\.venv\Scripts\python.exe synthetic_tables/src/main.py --min-cols 4 --max-cols 14
```

### DPIs

The defaults are `100` and `300`, but you can pass any positive DPI values.

```bash
synthetic_tables\.venv\Scripts\python.exe synthetic_tables/src/main.py --dpis 100 200 300
```

### Source formats

```bash
synthetic_tables\.venv\Scripts\python.exe synthetic_tables/src/main.py --source-formats html markdown
```

## LaTeX Prerequisites

LaTeX PDF rendering requires a real TeX engine. The renderer searches in this order:

1. `latexmk -pdf`
2. `pdflatex`
3. `tectonic`

If those executables are not available on `PATH`, the PDF renderer also looks at:

- `SYNTHETIC_TABLES_LATEXMK`
- `LATEXMK_PATH`
- `SYNTHETIC_TABLES_PDFLATEX`
- `PDFLATEX_PATH`
- `SYNTHETIC_TABLES_TECTONIC`
- `TECTONIC_PATH`

On Windows, installing MiKTeX is the most practical option. After installation, ensure `latexmk.exe` or `pdflatex.exe` is reachable on `PATH`, or set one of the environment variables above to the full executable path.

This is intentional behavior: if no supported TeX engine is found, LaTeX rendering fails immediately with a clear dependency error. It does not fall back to `reportlab`, `xhtml2pdf`, or any other non-TeX PDF renderer for the normal LaTeX pipeline.

If a TeX engine is present but both the creative compile and the TeX-backed safe-preview compile fail, the LaTeX render still fails instead of switching to a non-TeX renderer.

### Troubleshooting: No TeX Engine Found

If you request LaTeX rendering without `latexmk`, `pdflatex`, or `tectonic`, the run fails with an explicit `latex_engine_required` error. The message tells you that a real TeX engine is required, lists the executables that were searched, and reminds you about the supported environment variables for explicit paths.

For Windows users, the quickest fix is usually:

1. Install MiKTeX.
2. Confirm that `latexmk.exe` or `pdflatex.exe` is available.
3. If it is not on `PATH`, set `SYNTHETIC_TABLES_LATEXMK` or `SYNTHETIC_TABLES_PDFLATEX` to the full executable path before running the pipeline.

### Full example

```bash
synthetic_tables\.venv\Scripts\python.exe synthetic_tables/src/main.py ^
  --table-count 5 ^
  --visual-versions 2 ^
  --seed 77 ^
  --min-rows 40 ^
  --max-rows 90 ^
  --min-cols 5 ^
  --max-cols 10 ^
  --dpis 100 300 ^
  --source-formats html latex markdown
```

## Supported Data And Rendering Features

### Base column types

- `text_short`
- `text_long`
- `integer`
- `decimal`
- `percentage`
- `fraction`
- `date`
- `identifier`
- `alphanumeric_code`
- `symbolic_mixed`

### Style variations

- `font_family`
- `font_size_pt`
- `line_height`
- `border_style`
- `alignment_profile`
- `column_width_mode`
- `zebra_striping`
- `header_emphasis`
- `padding`

### Rendering stack

- HTML -> PDF via `playwright` + Chromium
- HTML fallback -> PDF via `weasyprint`
- HTML emergency fallback -> PDF via `xhtml2pdf`
- Markdown -> HTML -> PDF via `markdown` + internal `reportlab` table rendering
- PDF -> image via `pypdfium2`
- LaTeX creative mode -> PDF via local LaTeX engines with `latexmk -pdf` preferred, then `pdflatex`, then `tectonic`
- LaTeX safe-preview compatibility mode -> conservative standalone LaTeX compiled by the same TeX engine after a creative compile failure when the canonical table can be extracted
- LaTeX diagnostic fallback preview -> PDF via `reportlab` or `xhtml2pdf` only inside `latex_smoke_test.py` comparison bundles, not in the normal LaTeX render path

## Requirements Notes

`requirements.txt` reflects the direct dependencies used by the project code:

- `openpyxl` for XLSX export
- `Jinja2` for HTML and LaTeX templates
- `markdown` for Markdown-to-HTML conversion
- `playwright` for the default high-fidelity HTML-to-PDF path
- `weasyprint` for the higher-fidelity HTML fallback path
- `reportlab` for Markdown PDF rendering and LaTeX diagnostic fallback PDFs
- `xhtml2pdf` for emergency HTML fallback rendering and LaTeX diagnostic source-preview PDFs
- `pypdfium2` for PDF rasterization
- `Pillow` for image output support

Browser/runtime notes:

- Playwright needs a browser install step such as `python -m playwright install chromium`
- WeasyPrint may also require native text/layout libraries on some systems; if those are missing, the renderer falls through to the next supported fallback
- `xhtml2pdf` is intentionally still installed because the HTML renderer keeps it as the emergency fallback, and the LaTeX smoke-test diagnostics can still emit a forced source-preview PDF with it
- LaTeX PDF rendering depends on an external TeX engine being available; the pipeline looks for `latexmk`, `pdflatex`, or `tectonic` on `PATH`, through env vars like `SYNTHETIC_TABLES_LATEXMK` / `LATEXMK_PATH`, `SYNTHETIC_TABLES_PDFLATEX` / `PDFLATEX_PATH`, and `SYNTHETIC_TABLES_TECTONIC` / `TECTONIC_PATH`, plus common MiKTeX / TeX Live / TinyTeX locations on Windows
- The LaTeX backend now has two intentional modes:
  - creative templates for richer layouts and charts
  - `default_table.tex.j2` as the conservative compatibility/debug layout
- During PDF rendering, the LaTeX branch tries a creative compile first and then a safe-preview compile before failing the LaTeX render

## Limitations

Current limitations of the project:

- the pipeline generates synthetic tables, but not OCR annotations yet
- LaTeX creative mode still depends on the local engine supporting packages like `pgfplots` and `tcolorbox`; stricter installations may fall back to the safe-preview mode
- If no local LaTeX engine is installed, LaTeX rendering now fails intentionally with a clear dependency error instead of using a non-TeX PDF fallback
- HTML keeps its approved layout on the default Playwright path, but fallback renderers may still simplify layout if browser-grade rendering is unavailable
- page layouts are still table-centric, with one table per rendered document
- visual noise and document degradation are not yet modeled
- metadata focuses on file artifacts and generation settings, not geometric supervision

## Future Extensions For OCR And Table Extraction

Natural next extensions for OCR and table extraction include:

- table bounding box on the page
- bounding boxes for every cell
- per-token or per-line OCR text annotations
- visual noise injection
- blur simulation
- light rotation and skew
- scanning artifacts such as shadows, compression noise, and uneven illumination
- multiple tables on the same page
- borderless tables
- partially bordered tables
- richer pagination controls
- merged cells, nested headers, and footnotes

## End-to-End Summary

At the end of a successful run, the pipeline has:

- generated base structured tables
- exported CSV and XLSX versions
- produced multiple styled HTML, LaTeX, and Markdown variants
- rendered those variants into PDFs
- rasterized PDFs into page images at the requested DPI values
- written `tables.jsonl` and `samples.jsonl` so downstream tasks can consume the dataset programmatically
