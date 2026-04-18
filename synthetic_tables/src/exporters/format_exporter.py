"""Dispatch exports based on the requested file format."""

from __future__ import annotations

from pathlib import Path

from exporters.csv_exporter import CSVExporter
from exporters.xlsx_exporter import XLSXExporter
from generators.table_generator import GeneratedTable
from renderers.html_renderer import HTMLRenderer
from renderers.latex_renderer import LatexRenderer
from renderers.markdown_renderer import MarkdownRenderer
from styles.style_sampler import StyleSampler, TableStyle


class FormatExporter:
    """Route a generated table to the appropriate exporter."""

    def __init__(
        self,
        csv_exporter: CSVExporter | None = None,
        xlsx_exporter: XLSXExporter | None = None,
        html_renderer: HTMLRenderer | None = None,
        latex_renderer: LatexRenderer | None = None,
        markdown_renderer: MarkdownRenderer | None = None,
        style_sampler: StyleSampler | None = None,
    ) -> None:
        self.csv_exporter = csv_exporter or CSVExporter()
        self.xlsx_exporter = xlsx_exporter or XLSXExporter()
        self.html_renderer = html_renderer or HTMLRenderer()
        self.latex_renderer = latex_renderer or LatexRenderer()
        self.markdown_renderer = markdown_renderer or MarkdownRenderer()
        self.style_sampler = style_sampler or StyleSampler()

    def export(
        self,
        table: GeneratedTable,
        output_path: Path,
        format_name: str | None = None,
        style: TableStyle | None = None,
    ) -> Path:
        """Export a table using the requested format or the output suffix."""

        normalized_format = (format_name or output_path.suffix.lstrip(".")).lower()
        if normalized_format == "csv":
            return self.csv_exporter.export(table, output_path)
        if normalized_format == "xlsx":
            return self.xlsx_exporter.export(table, output_path)
        if normalized_format == "html":
            resolved_style = style or self.style_sampler.sample("html", table.table_id)
            return self.html_renderer.render_to_file(table, resolved_style, output_path)
        if normalized_format in {"tex", "latex"}:
            resolved_style = style or self.style_sampler.sample("latex", table.table_id)
            return self.latex_renderer.render_to_file(table, resolved_style, output_path)
        if normalized_format in {"md", "markdown"}:
            resolved_style = style or self.style_sampler.sample("markdown", table.table_id)
            return self.markdown_renderer.render_to_file(table, output_path, resolved_style)
        raise ValueError(f"Unsupported export format: {normalized_format}")

    def export_render_bundle(self, table: GeneratedTable, output_dir_map: dict[str, Path]) -> dict[str, Path]:
        """Export one table into the configured rendered formats."""

        rendered_paths: dict[str, Path] = {}
        for format_name, output_dir in output_dir_map.items():
            suffix = {"html": ".html", "latex": ".tex", "markdown": ".md"}[format_name]
            output_path = output_dir / f"{table.name}{suffix}"
            rendered_paths[format_name] = self.export(table, output_path, format_name=format_name)
        return rendered_paths
