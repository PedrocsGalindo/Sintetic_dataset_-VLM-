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

4. Optional: verify the `venv` is the one being used:

```bash
synthetic_tables\.venv\Scripts\python.exe -m pip list
```

## How To Run

Run the complete pipeline with defaults:

```bash
synthetic_tables\.venv\Scripts\python.exe synthetic_tables/src/main.py
```

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
- LaTeX -> PDF via `pdflatex` when available
- LaTeX fallback -> PDF preview via `reportlab` when table extraction succeeds
- LaTeX emergency fallback -> PDF preview via `xhtml2pdf` when `pdflatex` is unavailable or fails

## Requirements Notes

`requirements.txt` reflects the direct dependencies used by the project code:

- `openpyxl` for XLSX export
- `Jinja2` for HTML and LaTeX templates
- `markdown` for Markdown-to-HTML conversion
- `playwright` for the default high-fidelity HTML-to-PDF path
- `weasyprint` for the higher-fidelity HTML fallback path
- `reportlab` for Markdown PDF rendering and structured fallback PDFs
- `xhtml2pdf` for emergency HTML/LaTeX fallback rendering
- `pypdfium2` for PDF rasterization
- `Pillow` for image output support

Browser/runtime notes:

- Playwright needs a browser install step such as `python -m playwright install chromium`
- WeasyPrint may also require native text/layout libraries on some systems; if those are missing, the renderer falls through to the next supported fallback
- `xhtml2pdf` is intentionally still installed because the code keeps it as the final fallback, so it was not removed from the supported stack

## Limitations

Current limitations of the project:

- the pipeline generates synthetic tables, but not OCR annotations yet
- LaTeX PDF generation depends on `pdflatex`; without it, the pipeline uses a fallback preview renderer
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
