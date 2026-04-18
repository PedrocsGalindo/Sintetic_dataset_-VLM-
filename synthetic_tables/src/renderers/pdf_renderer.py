"""PDF rendering utilities for intermediate table representations."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from html import escape
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
from xhtml2pdf import pisa

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

    def render(self, source_path: Path, output_path: Path, source_format: str) -> PDFRenderResult:
        """Convert a source document into a PDF file."""

        normalized_format = source_format.lower()
        if not source_path.exists():
            raise FileNotFoundError(f"Source file not found for PDF rendering: {source_path}")
        ensure_parent_dir(output_path)

        if normalized_format == "html":
            renderer_name = self.render_html(source_path, output_path)
        elif normalized_format == "markdown":
            renderer_name = "reportlab-markdown-safe"
            markdown_text = source_path.read_text(encoding="utf-8")
            html_document = self._markdown_to_html_document(markdown_text, source_path.stem)
            parsed_document = self._parse_html_document(html_document, source_path.stem)
            self._render_html_table_to_pdf(parsed_document, output_path)
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
        """Render an HTML file to PDF using the HTML-only safe table path."""

        html_source = source_path.read_text(encoding="utf-8")
        parsed_document = self._parse_html_document(html_source, source_path.stem)
        self._render_html_table_to_pdf(parsed_document, output_path)
        return "reportlab-html-safe"

    def _html_to_pdf(self, html_content: str, output_path: Path) -> None:
        """Render an HTML string to PDF using xhtml2pdf."""

        with output_path.open("wb") as handle:
            result = pisa.CreatePDF(html_content, dest=handle, encoding="utf-8")
        if result.err:
            raise RuntimeError(f"Failed to render PDF with xhtml2pdf: {result.err}")

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
        """Convert Markdown text into a simple HTML document."""

        rendered_body = markdown_lib.markdown(markdown_text, extensions=["tables"])
        return (
            "<!DOCTYPE html><html><head><meta charset='utf-8'></head>"
            f"<body>{rendered_body}</body></html>"
        )

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
            ".table-wrap{width:100%;}"
            ".table-title{font-size:16pt;color:#2c5282;margin-bottom:12px;}"
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
