"""HTML renderer for generated tables."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from generators.table_generator import GeneratedTable
from styles.style_sampler import TableStyle
from utils.io import write_text_file


@dataclass(frozen=True)
class HTMLColumnView:
    """Represent one HTML-facing column configuration."""

    display_name: str
    alignment: str
    width: str


class HTMLRenderer:
    """Render a generated table to HTML using templates and CSS."""

    def __init__(self, template_dir: Path | None = None) -> None:
        resolved_template_dir = template_dir or Path(__file__).resolve().parents[1] / "styles" / "templates" / "html"
        self.environment = Environment(
            loader=FileSystemLoader(str(resolved_template_dir)),
            autoescape=select_autoescape(("html", "xml")),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, table: GeneratedTable, style: TableStyle) -> str:
        """Create an HTML representation for a generated table."""

        template = self.environment.get_template(style.template_name)
        resolved_width_mode = self._resolved_column_width_mode(style.column_width_mode, len(table.columns))
        columns = self._build_columns(table, style, resolved_width_mode)
        rows = [
            ["" if row[column_name] is None else str(row[column_name]) for column_name in table.columns]
            for row in table.rows
        ]
        css = {
            "border_style": self._map_border_style(style.border_style),
            "table_layout": "fixed" if resolved_width_mode == "fixed" else "auto",
            "header_emphasis_css": self._header_emphasis_css(style.header_emphasis),
        }
        return template.render(table=table, style=style, columns=columns, rows=rows, css=css)

    def render_to_file(self, table: GeneratedTable, style: TableStyle, output_path: Path) -> Path:
        """Write a rendered HTML file to disk."""

        html = self.render(table, style)
        write_text_file(output_path, html)
        return output_path

    def _build_columns(
        self,
        table: GeneratedTable,
        style: TableStyle,
        column_width_mode: str | None = None,
    ) -> list[HTMLColumnView]:
        """Build view-specific column settings for the template."""

        width_mode = column_width_mode or style.column_width_mode
        width = self._column_width(width_mode, len(table.columns))
        return [
            HTMLColumnView(
                display_name=column_schema.name.replace("_", " ").title(),
                alignment=self._alignment_for(column_schema.dtype, style.alignment_profile),
                width=width,
            )
            for column_schema in table.schema.columns
        ]

    @staticmethod
    def _column_width(column_width_mode: str, column_count: int) -> str:
        if column_width_mode == "fixed":
            return f"{100 / max(column_count, 1):.2f}%"
        if column_width_mode == "balanced":
            return f"{96 / max(column_count, 1):.2f}%"
        return "auto"

    @staticmethod
    def _resolved_column_width_mode(column_width_mode: str, column_count: int) -> str:
        """Avoid forcing equal-width columns on wide tables where readability would collapse."""

        if column_count >= 8:
            return "auto"
        return column_width_mode

    @staticmethod
    def _alignment_for(dtype: str, alignment_profile: str) -> str:
        if alignment_profile == "left":
            return "left"
        if alignment_profile == "center":
            return "center"
        if alignment_profile == "numeric_right":
            return "right" if dtype in {"integer", "decimal", "percentage", "fraction"} else "left"
        if dtype in {"integer", "decimal", "percentage", "fraction"}:
            return "right"
        if dtype in {"date", "identifier", "alphanumeric_code", "symbolic_mixed"}:
            return "center"
        return "left"

    @staticmethod
    def _map_border_style(border_style: str) -> str:
        mapping = {
            "solid": "solid",
            "dashed": "dashed",
            "double": "double",
            "minimal": "solid",
        }
        return mapping.get(border_style, "solid")

    @staticmethod
    def _header_emphasis_css(header_emphasis: str) -> str:
        mapping = {
            "bold": "font-weight: 700;",
            "caps": "font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;",
            "italic": "font-style: italic; font-weight: 600;",
            "smallcaps": "font-variant: small-caps; font-weight: 700;",
        }
        return mapping.get(header_emphasis, "font-weight: 700;")
