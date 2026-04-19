"""PDF rendering utilities for intermediate table representations."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from html import escape, unescape
from html.parser import HTMLParser
import re
from pathlib import Path
from tempfile import TemporaryDirectory

import markdown as markdown_lib
import pypdfium2 as pdfium
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle

from utils.io import ensure_parent_dir


@dataclass(frozen=True)
class PDFRenderResult:
    """Describe one rendered PDF artifact."""

    pdf_path: Path
    source_format: str
    renderer: str
    pages: int


@dataclass(frozen=True)
class ParsedTableDocument:
    """Represent the first table extracted from an input document."""

    title: str
    headers: list[str]
    rows: list[list[str]]


class _FirstTableParser(HTMLParser):
    """Extract the first table and a nearby title from simple generated HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.headers: list[str] = []
        self.rows: list[list[str]] = []

        self._in_title = False
        self._title_parts: list[str] = []
        self._in_table = False
        self._table_complete = False
        self._current_row: list[str] = []
        self._current_row_is_header = False
        self._current_cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "title"} and not self.title and not self._in_title:
            self._in_title = True
            self._title_parts = []
            return

        if self._table_complete:
            return

        if tag == "table" and not self._in_table:
            self._in_table = True
            return

        if not self._in_table:
            return

        if tag == "tr":
            self._current_row = []
            self._current_row_is_header = False
        elif tag in {"th", "td"}:
            self._current_cell_parts = []
            if tag == "th":
                self._current_row_is_header = True

    def handle_endtag(self, tag: str) -> None:
        if self._in_title and tag in {"h1", "title"}:
            title = self._collapse_whitespace("".join(self._title_parts))
            if title and not self.title:
                self.title = title
            self._in_title = False
            self._title_parts = []
            return

        if not self._in_table:
            return

        if tag in {"th", "td"} and self._current_cell_parts is not None:
            self._current_row.append(self._collapse_whitespace("".join(self._current_cell_parts)))
            self._current_cell_parts = None
            return

        if tag == "tr" and self._current_row:
            normalized_row = [cell for cell in self._current_row]
            if self._current_row_is_header and not self.headers:
                self.headers = normalized_row
            elif any(cell for cell in normalized_row):
                self.rows.append(normalized_row)
            self._current_row = []
            self._current_row_is_header = False
            return

        if tag == "table":
            self._in_table = False
            self._table_complete = True

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._current_cell_parts is not None:
            self._current_cell_parts.append(data)

    @staticmethod
    def _collapse_whitespace(text: str) -> str:
        return " ".join(text.split())


class PDFRenderer:
    """Convert HTML, Markdown, and LaTeX sources into PDF artifacts."""

    _HTML_PAGE_FORMAT = "A4"
    _HTML_PAGE_MARGIN_TOP = "9mm"
    _HTML_PAGE_MARGIN_RIGHT = "8mm"
    _HTML_PAGE_MARGIN_BOTTOM = "9mm"
    _HTML_PAGE_MARGIN_LEFT = "8mm"

    def render(self, source_path: Path, output_path: Path, source_format: str) -> PDFRenderResult:
        """Convert a source document into a PDF file."""

        normalized_format = source_format.lower()
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found for PDF rendering: {source_path}")
        ensure_parent_dir(output_path)

        if normalized_format == "html":
            renderer_name = self.render_html(source_path, output_path)
        elif normalized_format == "markdown":
            markdown_text = source_path.read_text(encoding="utf-8")
            html_document = self._markdown_to_html_document(markdown_text, source_path.stem)
            renderer_name = self._render_generated_html_document(
                html_content=html_document,
                output_path=output_path,
                source_stem=source_path.stem,
            )
        elif normalized_format == "latex":
            renderer_name = self._latex_to_pdf(source_path, output_path)
        else:
            raise ValueError(f"Unsupported source format for PDF rendering: {source_format}")

        return PDFRenderResult(
            pdf_path=output_path,
            source_format=normalized_format,
            renderer=renderer_name,
            pages=self._count_pages(output_path),
        )

    def render_html(self, source_path: Path, output_path: Path) -> str:
        """Render an HTML file to PDF while preserving the original HTML layout when possible."""

        html_source = source_path.read_text(encoding="utf-8")
        if self._render_html_with_playwright(source_path, output_path):
            return "playwright-chromium"

        if self._render_html_with_weasyprint(source_path, html_source, output_path):
            return "weasyprint-html"

        sanitized_html = self._sanitize_html_for_pdf(html_source)
        self._html_to_pdf(sanitized_html, output_path)
        return "xhtml2pdf-html-fallback"

    def _render_generated_html_document(self, html_content: str, output_path: Path, source_stem: str) -> str:
        """Render generated HTML content through the same high-fidelity HTML pipeline."""

        with TemporaryDirectory() as temp_dir:
            temp_html_path = Path(temp_dir) / f"{source_stem}.html"
            temp_html_path.write_text(html_content, encoding="utf-8")
            return self.render_html(temp_html_path, output_path)

    def _html_to_pdf(self, html_content: str, output_path: Path) -> None:
        """Render an HTML string to PDF using xhtml2pdf."""

        from xhtml2pdf import pisa

        with output_path.open("wb") as handle:
            result = pisa.CreatePDF(html_content, dest=handle, encoding="utf-8")
        if result.err:
            raise RuntimeError(f"Failed to render PDF with xhtml2pdf: {result.err}")

    def _render_html_with_playwright(self, source_path: Path, output_path: Path) -> bool:
        """Render the saved HTML file through Chromium for full CSS fidelity."""

        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError:
            return False

        page_css = self._html_print_css()
        source_uri = source_path.resolve().as_uri()

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_page()
                    page.goto(source_uri, wait_until="load")
                    page.emulate_media(media="print")
                    page.add_style_tag(content=page_css)
                    page.pdf(
                        path=str(output_path),
                        format=self._HTML_PAGE_FORMAT,
                        print_background=True,
                        prefer_css_page_size=False,
                        margin=self._playwright_pdf_margin(),
                    )
                finally:
                    browser.close()
        except (OSError, PlaywrightError):
            return False

        return True

    def _render_html_with_weasyprint(self, source_path: Path, html_source: str, output_path: Path) -> bool:
        """Render the original HTML/CSS with WeasyPrint when Chromium is unavailable."""

        try:
            from weasyprint import CSS, HTML
        except (ImportError, OSError):
            return False

        page_css = CSS(string=self._html_print_css())

        try:
            HTML(
                string=html_source,
                base_url=str(source_path.resolve().parent),
                media_type="print",
            ).write_pdf(str(output_path), stylesheets=[page_css])
        except OSError:
            return False

        return True

    def _html_print_css(self) -> str:
        """Inject print-only layout constraints for safer PDF page fit."""

        page_margin = (
            f"{self._HTML_PAGE_MARGIN_TOP} "
            f"{self._HTML_PAGE_MARGIN_RIGHT} "
            f"{self._HTML_PAGE_MARGIN_BOTTOM} "
            f"{self._HTML_PAGE_MARGIN_LEFT}"
        )
        return (
            "@page {"
            f"size: {self._HTML_PAGE_FORMAT};"
            f"margin: {page_margin};"
            "}"
            "@media print {"
            "html {"
            "box-sizing: border-box;"
            "-webkit-print-color-adjust: exact !important;"
            "print-color-adjust: exact !important;"
            "}"
            "*, *::before, *::after {"
            "box-sizing: inherit;"
            "}"
            "body {"
            "margin: 0 !important;"
            "padding: 0 !important;"
            "min-width: 0 !important;"
            "background: #ffffff !important;"
            "}"
            ".table-wrap, .sheet, .stream-sheet, .numbers-sheet {"
            "width: auto !important;"
            "max-width: 100% !important;"
            "margin: 0 auto !important;"
            "padding: 16px !important;"
            "overflow: hidden !important;"
            "box-shadow: none !important;"
            "break-inside: avoid-page;"
            "}"
            ".masthead, .header {"
            "gap: 14px !important;"
            "}"
            ".stats {"
            "min-width: 0 !important;"
            "max-width: 240px !important;"
            "}"
            ".hero-grid {"
            "grid-template-columns: minmax(0, 1.58fr) minmax(220px, 0.9fr) !important;"
            "gap: 16px !important;"
            "}"
            ".editorial-grid {"
            "grid-template-columns: minmax(0, 1.3fr) minmax(220px, 0.82fr) !important;"
            "gap: 16px !important;"
            "}"
            ".field-columns, .column-notes {"
            "gap: 12px !important;"
            "}"
            ".sidebar, .article-stack, .record-list, .note-stack, .block-grid, .stream-band, .ribbon {"
            "min-width: 0 !important;"
            "}"
            ".md-section, .md-block-grid, .md-block, .md-block-identity, .md-block-body, .md-block-flow, .md-fragment, .md-fragment-body, .md-fragment-pair {"
            "min-width: 0 !important;"
            "}"
            ".stream-line, .ribbon-row, .inline-summary, .article-block, .record-card, .sidebar-card, .mini-card, .note-card, .field-card, .block, .stat {"
            "max-width: 100% !important;"
            "}"
            ".keep-together {"
            "break-inside: avoid-page !important;"
            "page-break-inside: avoid !important;"
            "}"
            ".md-section > h2, .md-block-identity, .md-fragment > h4, .section-marker, .line-callout {"
            "break-after: avoid-page !important;"
            "page-break-after: avoid !important;"
            "}"
            "img, svg, canvas, table {"
            "max-width: 100% !important;"
            "}"
            "}"
        )

    def _playwright_pdf_margin(self) -> dict[str, str]:
        """Return explicit PDF margins for Playwright output."""

        return {
            "top": self._HTML_PAGE_MARGIN_TOP,
            "right": self._HTML_PAGE_MARGIN_RIGHT,
            "bottom": self._HTML_PAGE_MARGIN_BOTTOM,
            "left": self._HTML_PAGE_MARGIN_LEFT,
        }

    def _latex_to_pdf(self, source_path: Path, output_path: Path) -> str:
        """Render LaTeX to PDF when pdflatex is available, otherwise fallback."""

        pdflatex_path = shutil.which("pdflatex")
        if pdflatex_path is None:
            latex_source = source_path.read_text(encoding="utf-8")
            parsed_document = self._parse_generated_latex_document(latex_source, source_path.stem)
            if parsed_document.headers:
                self._render_html_table_to_pdf(parsed_document, output_path)
                return "reportlab-latex-fallback"
            fallback_html = self._latex_fallback_html(latex_source, source_path.stem)
            self._html_to_pdf(fallback_html, output_path)
            return "xhtml2pdf-latex-fallback"

        try:
            with TemporaryDirectory() as temp_dir:
                temp_dir_path = Path(temp_dir)
                temp_source_path = temp_dir_path / source_path.name
                temp_source_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
                subprocess.run(
                    [
                        pdflatex_path,
                        "-interaction=nonstopmode",
                        "-halt-on-error",
                        temp_source_path.name,
                    ],
                    cwd=temp_dir_path,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                compiled_pdf_path = temp_dir_path / f"{temp_source_path.stem}.pdf"
                output_path.write_bytes(compiled_pdf_path.read_bytes())
            return "pdflatex"
        except (OSError, subprocess.CalledProcessError):
            latex_source = source_path.read_text(encoding="utf-8")
            parsed_document = self._parse_generated_latex_document(latex_source, source_path.stem)
            if parsed_document.headers:
                self._render_html_table_to_pdf(parsed_document, output_path)
                return "reportlab-latex-fallback"
            fallback_html = self._latex_fallback_html(latex_source, source_path.stem)
            self._html_to_pdf(fallback_html, output_path)
            return "xhtml2pdf-latex-fallback"

    def _markdown_to_html_document(self, markdown_text: str, title: str) -> str:
        """Convert Markdown text into a standalone HTML document for browser-grade PDF rendering."""

        style_meta, cleaned_markdown = self._extract_markdown_style_metadata(markdown_text)
        rendered_body = markdown_lib.markdown(cleaned_markdown, extensions=["tables", "fenced_code"])
        theme_name = self._markdown_theme_name(style_meta.get("template_name", "default_markdown"))
        resolved_title = title.replace("_", " ").title()
        document_title, body_without_title = self._extract_markdown_title(rendered_body, resolved_title)
        intro_html, sections = self._split_markdown_sections(body_without_title)
        css = self._markdown_theme_css(style_meta, theme_name)
        body_html = self._compose_markdown_theme_body(
            title=document_title,
            intro_html=intro_html,
            sections=sections,
            theme_name=theme_name,
            style_meta=style_meta,
        )
        escaped_title = escape(document_title)
        return (
            "<!DOCTYPE html>"
            "<html lang='en'>"
            "<head>"
            "<meta charset='utf-8'>"
            f"<title>{escaped_title}</title>"
            f"<style>{css}</style>"
            "</head>"
            f"<body class='markdown-theme theme-{theme_name}'>"
            f"{body_html}"
            "</body>"
            "</html>"
        )

    def _extract_markdown_style_metadata(self, markdown_text: str) -> tuple[dict[str, object], str]:
        """Parse structured Markdown style metadata embedded at the top of the document."""

        metadata: dict[str, object] = {}
        cleaned_markdown = markdown_text
        comment_match = re.match(r"\s*<!--\s*(.*?)\s*-->\s*\n?", markdown_text, flags=re.DOTALL)
        if comment_match is None:
            return self._normalized_markdown_style_metadata(metadata), cleaned_markdown

        comment_body = comment_match.group(1).strip()
        cleaned_markdown = markdown_text[comment_match.end():]
        if comment_body.startswith("markdown-style:"):
            payload = comment_body.partition(":")[2].strip()
            try:
                parsed = json.loads(payload)
                if isinstance(parsed, dict):
                    metadata = parsed
            except json.JSONDecodeError:
                metadata = {}
        elif comment_body.startswith("style:"):
            legacy_payload = [part.strip() for part in comment_body.partition(":")[2].split("/") if part.strip()]
            if len(legacy_payload) >= 3:
                metadata = {
                    "font_family": legacy_payload[0],
                    "alignment_profile": legacy_payload[1],
                    "template_name": legacy_payload[2],
                }

        return self._normalized_markdown_style_metadata(metadata), cleaned_markdown

    def _normalized_markdown_style_metadata(self, metadata: dict[str, object]) -> dict[str, object]:
        """Fill missing Markdown style metadata with stable defaults."""

        defaults: dict[str, object] = {
            "template_name": "default_markdown",
            "font_family": "serif",
            "font_size_pt": 11,
            "line_height": 1.5,
            "alignment_profile": "mixed",
            "header_emphasis": "bold",
            "border_style": "solid",
            "text_color": "#1F2933",
            "header_background": "#DCEBFA",
            "border_color": "#5C6B7A",
            "background_color": "#FFFFFF",
            "accent_color": "#2C5282",
            "table_width": "92%",
            "zebra_striping": True,
        }
        normalized = defaults | metadata
        normalized["template_name"] = str(normalized["template_name"])
        normalized["font_family"] = str(normalized["font_family"])
        normalized["alignment_profile"] = str(normalized["alignment_profile"])
        normalized["header_emphasis"] = str(normalized["header_emphasis"])
        normalized["border_style"] = str(normalized["border_style"])
        normalized["text_color"] = str(normalized["text_color"])
        normalized["header_background"] = str(normalized["header_background"])
        normalized["border_color"] = str(normalized["border_color"])
        normalized["background_color"] = str(normalized["background_color"])
        normalized["accent_color"] = str(normalized["accent_color"])
        normalized["table_width"] = str(normalized["table_width"])
        normalized["font_size_pt"] = int(float(normalized["font_size_pt"]))
        normalized["line_height"] = float(normalized["line_height"])
        normalized["zebra_striping"] = bool(normalized["zebra_striping"])
        return normalized

    @staticmethod
    def _markdown_theme_name(template_name: str) -> str:
        """Map Markdown template names to richer HTML presentation themes."""

        mapping = {
            "default_markdown": "ledger",
            "markdown_records": "dossier",
            "markdown_mixed": "signal",
            "markdown_briefing": "briefing",
        }
        return mapping.get(template_name, "ledger")

    def _extract_markdown_title(self, rendered_body: str, fallback_title: str) -> tuple[str, str]:
        """Extract the leading H1 as the document title and remove it from the body."""

        match = re.search(r"<h1>(.*?)</h1>", rendered_body, flags=re.DOTALL | re.IGNORECASE)
        if match is None:
            return fallback_title, rendered_body

        title_html = match.group(1)
        title_text = unescape(re.sub(r"<.*?>", "", title_html)).strip() or fallback_title
        cleaned_body = rendered_body[:match.start()] + rendered_body[match.end():]
        return title_text, cleaned_body.strip()

    def _split_markdown_sections(self, body_html: str) -> tuple[str, list[dict[str, str]]]:
        """Split rendered Markdown HTML into themed H2 sections."""

        section_heading_pattern = re.compile(r"<h2>(.*?)</h2>", flags=re.DOTALL | re.IGNORECASE)
        matches = list(section_heading_pattern.finditer(body_html))
        if not matches:
            return "", [
                {
                    "slug": "document",
                    "heading_text": "Document",
                    "heading_html": "",
                    "content_html": self._wrap_markdown_section_content(body_html),
                }
            ]

        intro_html = body_html[: matches[0].start()].strip()
        sections: list[dict[str, str]] = []
        for index, match in enumerate(matches):
            content_start = match.end()
            content_end = matches[index + 1].start() if index + 1 < len(matches) else len(body_html)
            heading_html = match.group(0)
            heading_text = unescape(re.sub(r"<.*?>", "", match.group(1))).strip() or f"Section {index + 1}"
            sections.append(
                {
                    "slug": self._slugify(heading_text),
                    "heading_text": heading_text,
                    "heading_html": heading_html,
                    "content_html": self._wrap_markdown_section_content(body_html[content_start:content_end].strip()),
                }
            )
        return intro_html, sections

    def _wrap_markdown_section_content(self, content_html: str) -> str:
        """Decorate and group subsection-heavy Markdown HTML into reusable blocks."""

        decorated_html = self._decorate_markdown_section_html(content_html)
        subsection_pattern = re.compile(r"<h3>(.*?)</h3>", flags=re.DOTALL | re.IGNORECASE)
        matches = list(subsection_pattern.finditer(decorated_html))
        if not matches:
            flow_score = self._estimate_markdown_html_footprint(decorated_html)
            return (
                f"<div class='md-flow {self._markdown_footprint_class(flow_score)}"
                f"{self._markdown_keep_class(flow_score, limit=220)}'>"
                f"{decorated_html}"
                "</div>"
            )

        parts: list[str] = []
        intro_html = decorated_html[: matches[0].start()].strip()
        if intro_html:
            intro_score = self._estimate_markdown_html_footprint(intro_html)
            parts.append(
                f"<div class='md-section-intro {self._markdown_footprint_class(intro_score)}"
                f"{self._markdown_keep_class(intro_score, limit=160)}'>"
                f"{intro_html}"
                "</div>"
            )

        blocks: list[str] = []
        for index, match in enumerate(matches):
            block_start = match.end()
            block_end = matches[index + 1].start() if index + 1 < len(matches) else len(decorated_html)
            block_title = unescape(re.sub(r"<.*?>", "", match.group(1))).strip() or f"Block {index + 1}"
            block_content = decorated_html[block_start:block_end].strip()
            blocks.append(self._render_markdown_block(block_title, match.group(0), block_content))

        parts.append(f"<div class='md-block-grid'>{''.join(blocks)}</div>")
        return "".join(parts)

    def _render_markdown_block(self, block_title: str, heading_html: str, block_content: str) -> str:
        """Render one subsection block with grouped keep-together semantics."""

        body_html, block_score = self._wrap_markdown_block_body(block_content)
        origin_html = f"<p class='md-origin'>{escape(block_title)}</p>" if self._is_record_anchor(block_title) else ""
        return (
            f"<article class='md-block block-{self._slugify(block_title)} {self._markdown_footprint_class(block_score)}"
            f"{self._markdown_keep_class(block_score, limit=260)}'>"
            "<div class='md-block-identity'>"
            f"{origin_html}"
            f"{heading_html}"
            "</div>"
            f"<div class='md-block-body'>{body_html}</div>"
            "</article>"
        )

    def _wrap_markdown_block_body(self, block_content: str) -> tuple[str, int]:
        """Group block internals so summary and matrix fragments paginate as one unit when feasible."""

        intro_html, fragments = self._split_markdown_block_fragments(block_content)
        if not fragments:
            block_score = self._estimate_markdown_html_footprint(block_content)
            body_html = (
                f"<div class='md-block-flow {self._markdown_footprint_class(block_score)}"
                f"{self._markdown_keep_class(block_score, limit=220)}'>"
                f"{block_content}"
                "</div>"
            )
            return body_html, block_score

        body_parts: list[str] = []
        combined_score = 0

        if intro_html:
            intro_score = self._estimate_markdown_html_footprint(intro_html)
            combined_score += intro_score
            body_parts.append(
                f"<div class='md-block-flow {self._markdown_footprint_class(intro_score)}"
                f"{self._markdown_keep_class(intro_score, limit=170)}'>"
                f"{intro_html}"
                "</div>"
            )

        buffered_matrix_html: list[str] = []
        buffered_matrix_score = 0
        for fragment in fragments:
            fragment_html, fragment_score, fragment_kind = self._render_markdown_fragment(fragment)
            if fragment_kind == "matrix":
                buffered_matrix_html.append(fragment_html)
                buffered_matrix_score += fragment_score
                continue
            if buffered_matrix_html:
                body_parts.append(
                    self._render_markdown_fragment_pair(buffered_matrix_html, buffered_matrix_score)
                )
                combined_score += buffered_matrix_score
                buffered_matrix_html = []
                buffered_matrix_score = 0
            body_parts.append(fragment_html)
            combined_score += fragment_score

        if buffered_matrix_html:
            body_parts.append(self._render_markdown_fragment_pair(buffered_matrix_html, buffered_matrix_score))
            combined_score += buffered_matrix_score

        return "".join(body_parts), max(combined_score, self._estimate_markdown_html_footprint(block_content))

    def _split_markdown_block_fragments(self, block_content: str) -> tuple[str, list[dict[str, str]]]:
        """Split one record block into h4-level fragments while preserving leading summary flow."""

        fragment_pattern = re.compile(r"<h4>(.*?)</h4>", flags=re.DOTALL | re.IGNORECASE)
        matches = list(fragment_pattern.finditer(block_content))
        if not matches:
            return block_content, []

        intro_html = block_content[: matches[0].start()].strip()
        fragments: list[dict[str, str]] = []
        for index, match in enumerate(matches):
            fragment_start = match.end()
            fragment_end = matches[index + 1].start() if index + 1 < len(matches) else len(block_content)
            fragment_title = unescape(re.sub(r"<.*?>", "", match.group(1))).strip() or f"Fragment {index + 1}"
            fragments.append(
                {
                    "title_text": fragment_title,
                    "heading_html": match.group(0),
                    "content_html": block_content[fragment_start:fragment_end].strip(),
                }
            )
        return intro_html, fragments

    def _render_markdown_fragment(self, fragment: dict[str, str]) -> tuple[str, int, str]:
        """Render one fragment inside a record block with its own footprint estimate."""

        fragment_kind = self._markdown_fragment_kind(fragment["title_text"])
        fragment_score = self._estimate_markdown_html_footprint(
            fragment["heading_html"] + fragment["content_html"]
        )
        fragment_html = (
            f"<section class='md-fragment fragment-{fragment_kind} {self._markdown_footprint_class(fragment_score)}"
            f"{self._markdown_keep_class(fragment_score, limit=150)}'>"
            f"{fragment['heading_html']}"
            f"<div class='md-fragment-body'>{fragment['content_html']}</div>"
            "</section>"
        )
        return fragment_html, fragment_score, fragment_kind

    def _render_markdown_fragment_pair(self, fragment_html: list[str], pair_score: int) -> str:
        """Render a paired fragment cluster that should stay near one record anchor."""

        return (
            f"<div class='md-fragment-pair pair-matrix {self._markdown_footprint_class(pair_score)}"
            f"{self._markdown_keep_class(pair_score, limit=220)}'>"
            f"{''.join(fragment_html)}"
            "</div>"
        )

    def _estimate_markdown_html_footprint(self, html_content: str) -> int:
        """Estimate the final footprint of an assembled Markdown block using rendered HTML features."""

        plain_text = unescape(re.sub(r"<.*?>", " ", html_content))
        word_count = len(plain_text.split())
        char_count = len(plain_text)
        list_items = html_content.count("<li")
        tables = html_content.count("<table")
        quotes = html_content.count("md-quote")
        callouts = html_content.count("line-callout")
        markers = html_content.count("section-marker")
        subsections = html_content.count("<h4")
        code_blocks = html_content.count("<pre")
        return (
            max(24, word_count * 4)
            + min(char_count, 900) // 14
            + list_items * 10
            + tables * 72
            + quotes * 18
            + callouts * 16
            + markers * 10
            + subsections * 14
            + code_blocks * 28
        )

    @staticmethod
    def _markdown_footprint_class(footprint_score: int) -> str:
        """Map estimated footprint into stable CSS classes."""

        if footprint_score <= 120:
            return "footprint-compact"
        if footprint_score <= 220:
            return "footprint-balanced"
        if footprint_score <= 320:
            return "footprint-extended"
        return "footprint-sprawling"

    @staticmethod
    def _markdown_keep_class(footprint_score: int, limit: int) -> str:
        """Keep compact and medium fragments together, but let oversized blocks split naturally."""

        return " keep-together" if footprint_score <= limit else ""

    @staticmethod
    def _markdown_fragment_kind(title_text: str) -> str:
        """Classify Markdown fragments so paired matrices can paginate together."""

        normalized = title_text.strip().lower()
        if normalized.startswith("matrix "):
            return "matrix"
        if "free text" in normalized or "narrative" in normalized:
            return "narrative"
        if "detail" in normalized:
            return "details"
        return "section"

    def _decorate_markdown_section_html(self, html_content: str) -> str:
        """Add reusable semantic hooks to rendered Markdown HTML."""

        decorated = html_content
        decorated = decorated.replace("<table>", "<div class='table-shell'><table>")
        decorated = decorated.replace("</table>", "</table></div>")
        decorated = decorated.replace("<ul>", "<ul class='md-list'>")
        decorated = decorated.replace("<ol>", "<ol class='md-list md-list-ordered'>")
        decorated = decorated.replace("<blockquote>", "<blockquote class='md-quote'>")
        decorated = re.sub(
            r"<p><strong>(Summary|Insight|Highlight):</strong>\s*",
            lambda match: (
                f"<p class='line-callout {self._slugify(match.group(1))}-line'>"
                f"<span class='line-label'>{match.group(1)}</span> "
            ),
            decorated,
            flags=re.IGNORECASE,
        )
        decorated = re.sub(
            r"<p>(Details|Free Text|Key Fields|Fields):</p>",
            lambda match: f"<p class='section-marker'>{match.group(1)}</p>",
            decorated,
            flags=re.IGNORECASE,
        )
        return decorated

    def _compose_markdown_theme_body(
        self,
        title: str,
        intro_html: str,
        sections: list[dict[str, str]],
        theme_name: str,
        style_meta: dict[str, object],
    ) -> str:
        """Arrange themed Markdown sections into a richer document shell."""

        summary_sections: list[dict[str, str]] = []
        main_sections: list[dict[str, str]] = []
        for section in sections:
            if self._is_markdown_summary_section(section["slug"]):
                summary_sections.append(section)
            else:
                main_sections.append(section)

        if not main_sections:
            main_sections = summary_sections
            summary_sections = []

        summary_strip_html = ""
        if summary_sections:
            summary_strip_html = (
                f"<section class='summary-strip theme-{theme_name}'>"
                f"{''.join(self._render_markdown_section(section, compact=True) for section in summary_sections)}"
                "</section>"
            )

        main_content = (
            f"<div class='md-content theme-{theme_name}'>"
            f"{''.join(self._render_markdown_section(section) for section in main_sections)}"
            "</div>"
        )

        intro_panel = f"<div class='hero-intro'>{intro_html}</div>" if intro_html.strip() else ""
        template_label = escape(str(style_meta.get("template_name", "markdown")))
        return (
            "<section class='sheet'>"
            f"<header class='hero theme-{theme_name}'>"
            f"<p class='eyebrow'>{template_label.replace('_', ' ')}</p>"
            f"<h1>{escape(title)}</h1>"
            f"{intro_panel}"
            "</header>"
            f"<article class='markdown-body theme-{theme_name}'>"
            f"{summary_strip_html}"
            f"{main_content}"
            "</article>"
            "</section>"
        )

    def _render_markdown_section(self, section: dict[str, str], compact: bool = False) -> str:
        """Render one themed Markdown section container."""

        section_heading = section["heading_html"]
        section_body = section["content_html"]
        compact_class = " compact-summary" if compact else ""
        return (
            f"<section class='md-section section-{section['slug']}{compact_class}'>"
            f"{section_heading}"
            f"<div class='section-frame'>{section_body}</div>"
            "</section>"
        )

    def _markdown_theme_css(self, style_meta: dict[str, object], theme_name: str) -> str:
        """Return theme-specific CSS for Markdown-derived HTML documents."""

        font_stack = self._markdown_font_stack(str(style_meta["font_family"]))
        page_bg = str(style_meta["background_color"])
        text_color = str(style_meta["text_color"])
        accent_color = str(style_meta["accent_color"])
        border_color = str(style_meta["border_color"])
        header_background = str(style_meta["header_background"])
        font_size = int(style_meta["font_size_pt"])
        line_height = float(style_meta["line_height"])
        table_width = str(style_meta["table_width"])
        zebra = "rgba(148,163,184,0.08)" if bool(style_meta["zebra_striping"]) else "#ffffff"
        title_transform = "uppercase" if str(style_meta["header_emphasis"]) in {"caps", "smallcaps"} else "none"
        heading_letter_spacing = "0.08em" if str(style_meta["header_emphasis"]) == "caps" else "0.02em"
        border_radius = "0" if str(style_meta["border_style"]) == "minimal" else "18px" if str(style_meta["border_style"]) == "double" else "10px"
        border_style = "dashed" if str(style_meta["border_style"]) == "dashed" else "solid"

        theme_widths = {
            "ledger": "min(1040px, 95vw)",
            "dossier": "min(1180px, 96vw)",
            "signal": "min(1160px, 95vw)",
            "briefing": "min(1120px, 95vw)",
        }
        sheet_width = theme_widths.get(theme_name, "min(1080px, 95vw)")

        return "".join(
            [
                ":root{",
                f"--page-bg:{page_bg};",
                f"--text-color:{text_color};",
                f"--accent-color:{accent_color};",
                f"--border-color:{border_color};",
                f"--header-bg:{header_background};",
                f"--sheet-width:{sheet_width};",
                f"--table-width:{table_width};",
                f"--font-family:{font_stack};",
                f"--font-size:{font_size}pt;",
                f"--line-height:{line_height};",
                f"--radius:{border_radius};",
                f"--border-style:{border_style};",
                "}",
                "body{",
                "margin:0;",
                "padding:24px;",
                "background:linear-gradient(180deg, rgba(255,255,255,0.78), transparent 18%), linear-gradient(180deg, #eef4f8 0%, var(--page-bg) 100%);",
                "color:var(--text-color);",
                "font-family:var(--font-family);",
                "font-size:var(--font-size);",
                "line-height:var(--line-height);",
                "}",
                ".sheet{",
                "width:var(--sheet-width);",
                "margin:0 auto;",
                "padding:22px;",
                "background:rgba(255,255,255,0.98);",
                "border:1px var(--border-style) var(--border-color);",
                "box-shadow:0 14px 34px rgba(15,23,42,0.08);",
                "}",
                ".hero{margin:0 0 20px 0;}",
                ".hero h1{margin:0;color:var(--accent-color);font-size:2.1em;line-height:1.05;text-transform:",
                title_transform,
                ";letter-spacing:",
                heading_letter_spacing,
                ";}",
                ".eyebrow{margin:0 0 10px 0;font-size:0.76em;text-transform:uppercase;letter-spacing:0.12em;color:var(--accent-color);opacity:0.74;}",
                ".hero-intro{margin-top:12px;max-width:72ch;color:#556270;}",
                ".hero-intro > *:last-child{margin-bottom:0;}",
                ".markdown-body{display:grid;gap:18px;}",
                ".summary-strip{display:grid;grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));gap:14px;align-items:start;}",
                ".md-content{display:grid;gap:16px;min-width:0;}",
                ".md-section{min-width:0;}",
                ".md-section > h2{margin:0 0 12px 0;color:var(--accent-color);font-size:1.26em;line-height:1.15;}",
                ".section-frame{padding:16px;background:rgba(255,255,255,0.94);border:1px solid rgba(92,107,122,0.18);}",
                ".compact-summary > h2{margin-bottom:8px;font-size:1.02em;}",
                ".compact-summary .section-frame{padding:12px 14px;min-height:0;}",
                ".md-flow,.md-section-intro,.md-block,.md-block-identity,.md-block-body,.md-block-flow,.md-fragment,.md-fragment-body,.md-fragment-pair{min-width:0;}",
                ".md-flow > *:first-child,.md-section-intro > *:first-child,.md-block-flow > *:first-child,.md-fragment-body > *:first-child{margin-top:0;}",
                ".md-flow > *:last-child,.md-section-intro > *:last-child,.md-block-flow > *:last-child,.md-fragment-body > *:last-child{margin-bottom:0;}",
                ".md-block-grid{display:grid;gap:14px;}",
                ".md-block{padding:14px;background:linear-gradient(180deg, rgba(255,255,255,0.98), rgba(247,250,252,0.94));border-top:3px solid var(--accent-color);border-left:1px solid rgba(92,107,122,0.18);border-right:1px solid rgba(92,107,122,0.18);border-bottom:1px solid rgba(92,107,122,0.18);}",
                ".md-block-identity{display:grid;gap:4px;margin-bottom:10px;break-after:avoid-page;page-break-after:avoid;}",
                ".md-block-body{display:grid;gap:12px;}",
                ".md-block-flow,.md-fragment,.md-fragment-pair{display:grid;gap:10px;}",
                ".md-fragment{padding-top:10px;border-top:1px solid rgba(92,107,122,0.16);}",
                ".md-fragment:first-child{padding-top:0;border-top:none;}",
                ".md-fragment-body{display:grid;gap:8px;}",
                ".md-fragment-pair{padding:10px 12px;background:rgba(248,250,252,0.7);border:1px solid rgba(92,107,122,0.14);}",
                ".keep-together{break-inside:avoid-page;page-break-inside:avoid;}",
                ".md-section > h2,.md-block > h3,.md-fragment > h4,.section-marker,.line-callout{break-after:avoid-page;page-break-after:avoid;}",
                ".md-origin{margin:0 0 6px 0;font-size:0.74em;text-transform:uppercase;letter-spacing:0.08em;color:var(--accent-color);opacity:0.78;}",
                ".md-block > h3{margin:0;font-size:1em;color:var(--text-color);}",
                ".md-block h4,.md-flow h4{margin:0 0 8px 0;font-size:0.78em;text-transform:uppercase;letter-spacing:0.12em;color:var(--accent-color);}",
                ".md-list{margin:0;padding-left:1.2em;}",
                ".md-list li{margin:0.28em 0;}",
                ".line-callout{margin:0 0 10px 0;padding:10px 12px;background:linear-gradient(90deg, rgba(220,235,250,0.56), rgba(255,255,255,0.98) 24%);border-left:4px solid var(--accent-color);}",
                ".line-label{display:inline-block;margin-right:8px;font-weight:700;color:var(--accent-color);text-transform:uppercase;letter-spacing:0.06em;font-size:0.76em;}",
                ".section-marker{margin:0 0 8px 0;font-size:0.75em;text-transform:uppercase;letter-spacing:0.12em;color:var(--accent-color);}",
                ".table-shell{max-width:100%;margin:1em 0 0;overflow:hidden;border:1px solid rgba(92,107,122,0.2);}",
                ".markdown-body table{width:100%;border-collapse:collapse;table-layout:auto;margin:0;}",
                ".markdown-body th,.markdown-body td{border:1px solid rgba(92,107,122,0.2);padding:8px 10px;vertical-align:top;overflow-wrap:anywhere;}",
                ".markdown-body th{background:var(--header-bg);font-weight:700;text-align:left;}",
                ".markdown-body tbody tr:nth-child(even) td{background:",
                zebra,
                ";}",
                ".md-quote{margin:0 0 12px 0;padding:12px 14px;background:rgba(220,235,250,0.36);border-left:4px solid var(--accent-color);color:#5b6775;}",
                ".markdown-body code{padding:0.08em 0.32em;border-radius:4px;background:rgba(226,232,240,0.7);font-family:'Courier New', monospace;font-size:0.94em;}",
                ".markdown-body pre{margin:0 0 12px 0;padding:12px 14px;background:#f8fafc;border:1px solid rgba(92,107,122,0.18);overflow:auto;}",
                ".markdown-body pre code{padding:0;background:transparent;}",
                ".markdown-body hr{border:none;border-top:1px solid rgba(92,107,122,0.18);margin:1.25em 0;}",
                ".theme-ledger .hero{padding:0 0 14px 0;border-bottom:2px solid rgba(92,107,122,0.16);}",
                ".theme-ledger .section-frame{padding:0;background:transparent;border:none;}",
                ".theme-ledger .table-shell{margin-top:0;border-width:0 0 1px 0;}",
                ".theme-ledger .md-block-grid{grid-template-columns:1fr;}",
                ".theme-dossier .hero{display:grid;gap:12px;align-items:end;}",
                ".theme-dossier .hero-intro{padding:12px 14px;background:linear-gradient(180deg, rgba(220,235,250,0.4), rgba(255,255,255,0.98));border:1px solid rgba(92,107,122,0.18);}",
                ".theme-dossier .summary-strip .md-list{display:grid;grid-template-columns:repeat(auto-fit, minmax(140px, 1fr));gap:8px;list-style:none;padding:0;}",
                ".theme-dossier .summary-strip .md-list li{margin:0;padding:10px 12px;border:1px solid rgba(92,107,122,0.16);background:rgba(248,250,252,0.92);}",
                ".theme-dossier .section-records .md-block-grid,.theme-dossier .section-record-notes .md-block-grid{grid-template-columns:repeat(2, minmax(0,1fr));}",
                ".theme-signal .hero{padding:16px 18px;background:linear-gradient(135deg, rgba(220,235,250,0.72), rgba(255,255,255,0.96));border-left:6px solid var(--accent-color);}",
                ".theme-signal .md-section > h2{padding-bottom:6px;border-bottom:1px solid rgba(92,107,122,0.16);}",
                ".theme-signal .summary-strip .md-list{display:grid;grid-template-columns:repeat(auto-fit, minmax(150px, 1fr));gap:8px;list-style:none;padding:0;}",
                ".theme-signal .summary-strip .md-list li{margin:0;padding:10px 12px;border:1px solid rgba(92,107,122,0.18);background:rgba(255,255,255,0.96);}",
                ".theme-signal .section-record-notes .md-block{border-top-width:4px;}",
                ".theme-signal .section-record-notes .md-block-grid{grid-template-columns:repeat(2, minmax(0,1fr));gap:12px;}",
                ".theme-briefing .hero{padding:18px 20px;background:linear-gradient(180deg, rgba(255,255,255,0.96), rgba(243,247,252,0.94));border-top:4px solid var(--accent-color);}",
                ".theme-briefing .hero h1{font-size:2.24em;}",
                ".theme-briefing .summary-strip{grid-template-columns:repeat(auto-fit, minmax(240px, 1fr));}",
                ".theme-briefing .summary-strip .section-frame{background:linear-gradient(180deg, rgba(220,235,250,0.34), rgba(255,255,255,0.98));}",
                ".theme-briefing .section-highlights .md-block-grid{grid-template-columns:repeat(2, minmax(0,1fr));}",
                ".theme-briefing .section-full-index .md-list{display:grid;grid-template-columns:repeat(2, minmax(0,1fr));gap:10px;padding-left:0;list-style:none;}",
                ".theme-briefing .section-full-index .md-list li{margin:0;padding:10px 12px;border-bottom:1px dashed rgba(92,107,122,0.24);background:rgba(255,255,255,0.9);}",
                ".theme-briefing .section-highlights .md-origin{margin-bottom:4px;}",
            ]
        )

    @staticmethod
    def _markdown_font_stack(font_family: str) -> str:
        """Map sampled Markdown font families to browser-friendly stacks."""

        normalized = font_family.strip().lower()
        if normalized == "serif":
            return "Georgia, 'Times New Roman', serif"
        if normalized == "sans-serif":
            return "'Trebuchet MS', Verdana, sans-serif"
        if normalized == "monospace":
            return "'Courier New', Consolas, monospace"
        if "garamond" in normalized:
            return "Garamond, Georgia, serif"
        if "verdana" in normalized or "tahoma" in normalized:
            return f"'{font_family}', Verdana, sans-serif"
        return f"'{font_family}', Georgia, serif"

    @staticmethod
    def _slugify(text: str) -> str:
        """Convert heading text into a stable CSS-friendly slug."""

        return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"

    @staticmethod
    def _is_markdown_summary_section(slug: str) -> bool:
        """Identify Markdown sections that should be promoted into the compact top summary band."""

        return slug in {"dataset-snapshot", "overview", "briefing"}

    @staticmethod
    def _is_record_anchor(text: str) -> bool:
        """Identify subsection headings that act as row-traceable record anchors."""

        return bool(re.match(r"record\s+\d+", text.strip(), flags=re.IGNORECASE))

    def _parse_html_document(self, html_content: str, fallback_title: str) -> ParsedTableDocument:
        """Extract the first table and normalize its rows for PDF-safe rendering."""

        parser = _FirstTableParser()
        parser.feed(html_content)

        column_count = len(parser.headers)
        if column_count == 0:
            column_count = max((len(row) for row in parser.rows), default=0)

        if column_count == 0:
            return ParsedTableDocument(title=fallback_title, headers=[], rows=[])

        headers = parser.headers or [f"Column {index + 1}" for index in range(column_count)]
        if len(headers) < column_count:
            headers = headers + [f"Column {index + 1}" for index in range(len(headers), column_count)]
        headers = headers[:column_count]

        normalized_rows = [
            (row + [""] * column_count)[:column_count]
            for row in parser.rows
        ]
        title = parser.title or fallback_title
        return ParsedTableDocument(title=title, headers=headers, rows=normalized_rows)

    def _parse_generated_latex_document(self, latex_source: str, fallback_title: str) -> ParsedTableDocument:
        """Extract the generated longtable data from the controlled LaTeX template."""

        title_match = re.search(r"\\noindent\{\\Large\s+(.*?)\}\\\\\[8pt\]", latex_source, flags=re.DOTALL)
        title = self._unescape_latex(title_match.group(1).strip()) if title_match else fallback_title

        table_match = re.search(
            r"\\begin\{longtable\}\{.*?\}(.*?)\\end\{longtable\}",
            latex_source,
            flags=re.DOTALL,
        )
        if table_match is None:
            return ParsedTableDocument(title=title, headers=[], rows=[])

        table_content = table_match.group(1)
        first_head_part, _, remainder = table_content.partition(r"\endfirsthead")
        _, has_endhead, body_part = remainder.partition(r"\endhead")
        if not has_endhead:
            body_part = remainder

        header_row = self._first_latex_row(first_head_part)
        body_rows = self._latex_rows(body_part)
        if not header_row:
            return ParsedTableDocument(title=title, headers=[], rows=[])

        column_count = len(header_row)
        normalized_rows = [(row + [""] * column_count)[:column_count] for row in body_rows if any(cell for cell in row)]
        return ParsedTableDocument(title=title, headers=header_row, rows=normalized_rows)

    def _build_pdf_safe_html(self, document: ParsedTableDocument) -> str:
        """Render a minimal HTML document that xhtml2pdf can lay out more reliably."""

        if not document.headers:
            return self._fallback_pdf_html(document.title)

        column_kinds = [self._infer_column_kind(document.headers, document.rows, index) for index in range(len(document.headers))]
        column_widths = self._calculate_column_widths(document.headers, document.rows, column_kinds)
        alignments = [self._alignment_for_kind(kind) for kind in column_kinds]

        column_count = len(document.headers)
        orientation = "landscape" if column_count >= 8 else "portrait"
        font_size_pt = 7 if column_count >= 10 else 8 if column_count >= 8 else 9 if column_count >= 6 else 10
        cell_padding = 4 if column_count >= 10 else 5 if column_count >= 8 else 6

        colgroup = "".join(f"<col style='width:{width:.2f}%;' />" for width in column_widths)
        header_cells = "".join(
            f"<th style='width:{column_widths[index]:.2f}%; text-align:{alignments[index]};'>{escape(header)}</th>"
            for index, header in enumerate(document.headers)
        )

        body_rows: list[str] = []
        for row_index, row in enumerate(document.rows):
            background = "#f8fafc" if row_index % 2 else "#ffffff"
            cell_html = "".join(
                (
                    f"<td style='text-align:{alignments[column_index]}; background-color:{background};'>"
                    f"{escape(cell)}"
                    "</td>"
                )
                for column_index, cell in enumerate(row)
            )
            body_rows.append(f"<tr>{cell_html}</tr>")

        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>"
            f"@page {{ size: A4 {orientation}; margin: 14mm 10mm; }}"
            "body{font-family:Helvetica,Arial,sans-serif;color:#1f2933;}"
            f"h1{{font-size:{font_size_pt + 7}pt;color:#2c5282;margin:0 0 10pt 0;}}"
            "table{width:100%;border-collapse:collapse;table-layout:fixed;}"
            f"th,td{{border:1px solid #64748b;padding:{cell_padding}px;vertical-align:top;word-wrap:break-word;}}"
            "th{background-color:#dcebfa;font-weight:bold;}"
            "tr{page-break-inside:avoid;}"
            "</style></head>"
            f"<body><h1>{escape(document.title)}</h1>"
            f"<table><colgroup>{colgroup}</colgroup><thead><tr>{header_cells}</tr></thead>"
            f"<tbody>{''.join(body_rows)}</tbody></table></body></html>"
        )

    def _sanitize_html_for_pdf(self, html_content: str) -> str:
        """Replace advanced CSS with a simpler stylesheet for xhtml2pdf."""

        simplified_css = (
            "<style>"
            "body{font-family:Helvetica,Arial,sans-serif;font-size:10pt;color:#1f2933;padding:18px;}"
            ".table-wrap,.sheet,.stream-sheet,.numbers-sheet{width:100%;background:#ffffff;"
            "border:1px solid #64748b;padding:14px;box-sizing:border-box;}"
            ".masthead,.header{display:block;}"
            ".stats,.block-grid{display:block;}"
            ".stat,.block,.record-card{display:block;margin-bottom:10px;padding:10px;"
            "border:1px solid #cbd5e0;background:#f8fafc;}"
            ".table-title,.title{font-size:16pt;color:#2c5282;margin-bottom:12px;}"
            ".subtitle,.summary,.headline,.field,.stream-line{font-size:10pt;}"
            ".record-columns,.stream{display:block;}"
            ".record-card,.stream-line,.block{page-break-inside:avoid;}"
            ".line-label,.record-tag,.chip-label,.stat-label{font-weight:bold;color:#2c5282;}"
            ".chip-value,.stat-value{font-weight:bold;}"
            "table{width:100%;border-collapse:collapse;table-layout:auto;}"
            "th,td{border:1px solid #64748b;padding:6px;vertical-align:top;}"
            "th{background:#dcebfa;font-weight:bold;}"
            "tbody tr:nth-child(even) td{background:#f8fafc;}"
            "</style>"
        )
        without_style = re.sub(r"<style.*?</style>", simplified_css, html_content, flags=re.DOTALL | re.IGNORECASE)
        if "<style" not in without_style.lower():
            without_style = without_style.replace("</head>", f"{simplified_css}</head>")
        return without_style

    def _fallback_pdf_html(self, title: str) -> str:
        """Return a minimal placeholder when no table could be extracted."""

        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>"
            "@page { size: A4 portrait; margin: 18mm 14mm; }"
            "body{font-family:Helvetica,Arial,sans-serif;color:#1f2933;}"
            "h1{font-size:16pt;color:#2c5282;margin:0 0 12pt 0;}"
            "p{font-size:10pt;}"
            "</style></head>"
            f"<body><h1>{escape(title)}</h1><p>No table content was extracted for PDF rendering.</p></body></html>"
        )

    def _render_html_table_to_pdf(self, document: ParsedTableDocument, output_path: Path) -> None:
        """Render the parsed HTML table directly with ReportLab for more stable pagination."""

        ensure_parent_dir(output_path)
        if not document.headers:
            self._html_to_pdf(self._fallback_pdf_html(document.title), output_path)
            return

        column_count = len(document.headers)
        column_kinds = [self._infer_column_kind(document.headers, document.rows, index) for index in range(column_count)]
        column_width_ratios = self._calculate_column_widths(document.headers, document.rows, column_kinds)
        long_text_columns = sum(kind == "long_text" for kind in column_kinds)

        page_size = landscape(A4) if column_count >= 7 or long_text_columns >= 3 else A4
        if page_size == landscape(A4):
            left_margin = 6 * mm
            right_margin = 6 * mm
            top_margin = 9 * mm
            bottom_margin = 9 * mm
        else:
            left_margin = 9 * mm
            right_margin = 9 * mm
            top_margin = 11 * mm
            bottom_margin = 11 * mm

        page_width, _ = page_size
        usable_width = page_width - left_margin - right_margin
        column_widths = [usable_width * (ratio / 100.0) for ratio in column_width_ratios]

        body_font_size = 6.7 if column_count >= 10 else 7.2 if column_count >= 8 else 8 if column_count >= 6 else 9
        header_font_size = body_font_size + 0.5
        title_font_size = body_font_size + 5
        leading = body_font_size + 2

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "HTMLDebugTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=title_font_size,
            leading=title_font_size + 2,
            textColor=colors.HexColor("#2c5282"),
            spaceAfter=8,
        )
        header_styles = [
            ParagraphStyle(
                f"HeaderCol{index}",
                parent=styles["BodyText"],
                fontName="Helvetica-Bold",
                fontSize=header_font_size,
                leading=header_font_size + 2,
                textColor=colors.HexColor("#1f2933"),
                alignment=self._reportlab_alignment(self._alignment_for_kind(column_kinds[index])),
                wordWrap="LTR",
            )
            for index in range(column_count)
        ]
        body_styles = [
            ParagraphStyle(
                f"BodyCol{index}",
                parent=styles["BodyText"],
                fontName="Helvetica",
                fontSize=body_font_size,
                leading=leading,
                textColor=colors.HexColor("#1f2933"),
                alignment=self._reportlab_alignment(self._alignment_for_kind(column_kinds[index])),
                wordWrap="LTR",
            )
            for index in range(column_count)
        ]

        def paragraph(text: str, style: ParagraphStyle) -> Paragraph:
            normalized = escape(text or "")
            return Paragraph(normalized if normalized else "&nbsp;", style)

        table_data: list[list[Paragraph]] = [
            [paragraph(header, header_styles[index]) for index, header in enumerate(document.headers)]
        ]
        for row in document.rows:
            table_data.append([paragraph(cell, body_styles[index]) for index, cell in enumerate(row)])

        table = LongTable(
            table_data,
            colWidths=column_widths,
            repeatRows=1,
            splitByRow=1,
            hAlign="LEFT",
        )

        style_commands: list[tuple] = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dcebfa")),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1f2933")),
            ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#64748b")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]

        for row_index in range(1, len(table_data)):
            if row_index % 2 == 0:
                style_commands.append(
                    ("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#f8fafc"))
                )

        table.setStyle(TableStyle(style_commands))

        document_template = SimpleDocTemplate(
            str(output_path),
            pagesize=page_size,
            leftMargin=left_margin,
            rightMargin=right_margin,
            topMargin=top_margin,
            bottomMargin=bottom_margin,
            title=document.title,
        )
        story = [
            Paragraph(escape(document.title), title_style),
            Spacer(1, 2),
            table,
        ]
        document_template.build(story)

    def _infer_column_kind(self, headers: list[str], rows: list[list[str]], column_index: int) -> str:
        """Infer a coarse content type to guide width and alignment decisions."""

        header = headers[column_index].strip()
        values = [row[column_index] for row in rows[:30]]
        non_empty_values = [value.strip() for value in values if value and value.strip()]
        if not non_empty_values:
            return "text"

        numeric_ratio = self._match_ratio(non_empty_values, self._is_numeric_like)
        date_ratio = self._match_ratio(non_empty_values, self._is_date_like)
        code_ratio = self._match_ratio(non_empty_values, self._is_code_like)

        if numeric_ratio >= 0.85:
            return "numeric"
        if date_ratio >= 0.85 or "date" in header.lower():
            return "date"
        if code_ratio >= 0.85 or "code" in header.lower() or "token" in header.lower():
            return "code"

        values_with_spaces = sum(" " in value for value in non_empty_values)
        average_length = sum(len(value) for value in non_empty_values) / len(non_empty_values)
        max_length = max(len(value) for value in non_empty_values)
        if average_length <= 13 and max_length <= 22:
            return "compact_text"
        if values_with_spaces >= max(1, len(non_empty_values) // 2):
            return "long_text" if average_length >= 18 else "text"
        if average_length >= 18:
            return "long_text"
        return "text"

    def _calculate_column_widths(
        self,
        headers: list[str],
        rows: list[list[str]],
        column_kinds: list[str],
    ) -> list[float]:
        """Estimate column widths that sum to 100% for PDF-safe tables."""

        scores = [
            self._column_score(headers[column_index], [row[column_index] for row in rows[:25]], column_kinds[column_index])
            for column_index in range(len(headers))
        ]
        minimums = self._minimum_widths(column_kinds)
        total_score = sum(scores) or float(len(scores))
        widths = [(score / total_score) * 100.0 for score in scores]

        deficit = 0.0
        adjustable_indexes: list[int] = []
        for index, width in enumerate(widths):
            minimum = minimums[index]
            if width < minimum:
                deficit += minimum - width
                widths[index] = minimum
            else:
                adjustable_indexes.append(index)

        if deficit > 0 and adjustable_indexes:
            reducible = sum(widths[index] - minimums[index] for index in adjustable_indexes)
            if reducible > 0:
                for index in adjustable_indexes:
                    room = widths[index] - minimums[index]
                    widths[index] -= deficit * (room / reducible)

        total_width = sum(widths)
        if total_width <= 0:
            return [round(100.0 / len(headers), 2)] * len(headers)

        widths = [(width / total_width) * 100.0 for width in widths]
        widths[-1] += 100.0 - sum(widths)
        return widths

    def _minimum_widths(self, column_kinds: list[str]) -> list[float]:
        """Choose conservative minimum widths so wide tables still fit on the page."""

        column_count = len(column_kinds)
        if column_count >= 10:
            minimum_map = {
                "numeric": 5.0,
                "date": 6.4,
                "code": 5.8,
                "compact_text": 6.2,
                "text": 7.2,
                "long_text": 11.5,
            }
        elif column_count >= 8:
            minimum_map = {
                "numeric": 5.6,
                "date": 7.0,
                "code": 6.6,
                "compact_text": 7.0,
                "text": 8.4,
                "long_text": 12.0,
            }
        else:
            minimum_map = {
                "numeric": 7.5,
                "date": 9.0,
                "code": 8.5,
                "compact_text": 9.0,
                "text": 10.5,
                "long_text": 13.0,
            }
        return [minimum_map.get(kind, 8.0) for kind in column_kinds]

    def _column_score(self, header: str, values: list[str], column_kind: str) -> float:
        """Score a column based on content density so width can be allocated proportionally."""

        non_empty_values = [value.strip() for value in [header, *values] if value and value.strip()]
        lengths = [min(len(value), 60) for value in non_empty_values] or [len(header)]
        letter_counts = [
            min(sum(1 for character in value if character.isalpha()), 60)
            for value in non_empty_values
        ] or [sum(1 for character in header if character.isalpha())]
        average_length = sum(lengths) / len(lengths)
        average_letters = sum(letter_counts) / len(letter_counts)
        max_length = max(lengths)

        score = 1.2 + min(len(header), 24) * 0.08 + average_length * 0.10 + max_length * 0.025
        multiplier_map = {
            "numeric": 0.65,
            "date": 0.75,
            "code": 0.80,
            "compact_text": 0.72,
            "text": 1.0,
            "long_text": 1.80,
        }
        text_bonus_map = {
            "compact_text": 0.03,
            "text": 0.06,
            "long_text": 0.11,
        }
        score += average_letters * text_bonus_map.get(column_kind, 0.0)
        return score * multiplier_map.get(column_kind, 1.0)

    @staticmethod
    def _match_ratio(values: list[str], predicate: callable) -> float:
        """Measure how consistently a column matches one structural pattern."""

        if not values:
            return 0.0
        matches = sum(1 for value in values if predicate(value))
        return matches / len(values)

    @staticmethod
    def _alignment_for_kind(column_kind: str) -> str:
        if column_kind == "numeric":
            return "right"
        if column_kind in {"date", "code"}:
            return "center"
        return "left"

    @staticmethod
    def _reportlab_alignment(alignment: str) -> int:
        mapping = {
            "left": 0,
            "center": 1,
            "right": 2,
        }
        return mapping.get(alignment, 0)

    @staticmethod
    def _is_numeric_like(value: str) -> bool:
        normalized = value.strip().replace(",", "")
        return bool(re.fullmatch(r"-?\d+(?:\.\d+)?%?", normalized) or re.fullmatch(r"\d+/\d+", normalized))

    @staticmethod
    def _is_date_like(value: str) -> bool:
        normalized = value.strip()
        return bool(re.fullmatch(r"\d{1,4}[-/]\d{1,2}[-/]\d{1,4}", normalized))

    @staticmethod
    def _is_code_like(value: str) -> bool:
        normalized = value.strip()
        if " " in normalized or not normalized:
            return False
        if len(normalized) > 16:
            return False
        has_letter = any(character.isalpha() for character in normalized)
        has_digit = any(character.isdigit() for character in normalized)
        has_symbol = any(not character.isalnum() for character in normalized)
        return has_letter and (has_digit or has_symbol)

    def _latex_fallback_html(self, latex_source: str, title: str) -> str:
        """Create a simple fallback HTML document for LaTeX sources."""

        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>"
            "body{font-family:'Courier New',monospace;padding:24px;color:#2d3748;}"
            "h1{font-family:Arial,sans-serif;color:#9c4221;}"
            "pre{white-space:pre-wrap;border:1px solid #cbd5e0;padding:16px;background:#fffaf0;}"
            "</style></head>"
            f"<body><h1>{escape(title)} (LaTeX fallback preview)</h1>"
            f"<pre>{escape(latex_source)}</pre></body></html>"
        )

    def _first_latex_row(self, latex_block: str) -> list[str]:
        """Return the first parsed LaTeX table row from a block."""

        rows = self._latex_rows(latex_block, limit=1)
        return rows[0] if rows else []

    def _latex_rows(self, latex_block: str, limit: int | None = None) -> list[list[str]]:
        """Parse row lines from the generated longtable body."""

        rows: list[list[str]] = []
        for raw_line in latex_block.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("\\"):
                continue
            if not line.endswith(r"\\"):
                continue

            row_text = line[:-2].strip()
            if not row_text:
                continue

            cells = [
                self._unescape_latex(cell.strip())
                for cell in re.split(r"(?<!\\)&", row_text)
            ]
            rows.append(cells)

            if limit is not None and len(rows) >= limit:
                break

        return rows

    @staticmethod
    def _unescape_latex(value: str) -> str:
        """Convert the renderer's escaped LaTeX text back into plain text."""

        replacements = {
            r"\textbackslash{}": "\\",
            r"\&": "&",
            r"\%": "%",
            r"\$": "$",
            r"\#": "#",
            r"\_": "_",
            r"\{": "{",
            r"\}": "}",
            r"\textasciitilde{}": "~",
            r"\textasciicircum{}": "^",
        }
        unescaped = value
        for escaped, plain in replacements.items():
            unescaped = unescaped.replace(escaped, plain)
        return unescaped

    @staticmethod
    def _count_pages(pdf_path: Path) -> int:
        """Count the number of pages in a rendered PDF."""

        document = pdfium.PdfDocument(str(pdf_path))
        try:
            page_count = len(document)
            if page_count <= 0:
                raise ValueError(f"Rendered PDF has no pages: {pdf_path}")
            return page_count
        finally:
            document.close()
