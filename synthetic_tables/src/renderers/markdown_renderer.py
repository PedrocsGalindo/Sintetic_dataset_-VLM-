"""Markdown renderer for generated tables."""

from __future__ import annotations

from html import escape
from pathlib import Path

from generators.table_generator import GeneratedTable
from styles.style_sampler import TableStyle
from utils.io import write_text_file


class MarkdownRenderer:
    """Render a generated table to GitHub-flavored Markdown."""

    def render(self, table: GeneratedTable, style: TableStyle | None = None) -> str:
        """Create a Markdown table representation."""

        header = "| " + " | ".join(self._display_name(column) for column in table.columns) + " |"
        separator = "| " + " | ".join(self._separator_cells(table, style)) + " |"
        rows = [
            "| " + " | ".join(self._escape_cell(row.get(column)) for column in table.columns) + " |"
            for row in table.rows
        ]
        title = f"<!-- style: {style.font_family if style else 'default'} / {style.alignment_profile if style else 'default'} -->"
        rendered_title = self._display_name(table.name)
        return "\n".join([title, f"# {rendered_title}", "", header, separator, *rows])

    def render_to_file(self, table: GeneratedTable, output_path: Path, style: TableStyle | None = None) -> Path:
        """Write a rendered Markdown file to disk."""

        markdown = self.render(table, style)
        write_text_file(output_path, markdown)
        return output_path

    def _separator_cells(self, table: GeneratedTable, style: TableStyle | None) -> list[str]:
        """Build Markdown alignment cells."""

        alignment_profile = style.alignment_profile if style else "mixed"
        cells: list[str] = []
        for column in table.schema.columns:
            alignment = self._alignment_for(column.dtype, alignment_profile)
            if alignment == "right":
                cells.append("---:")
            elif alignment == "center":
                cells.append(":---:")
            else:
                cells.append(":---")
        return cells

    @staticmethod
    def _display_name(value: str) -> str:
        """Convert internal slugs into reader-friendly labels."""

        return value.replace("_", " ").title()

    @staticmethod
    def _escape_cell(value: object) -> str:
        """Escape content that would otherwise break Markdown table parsing."""

        if value is None:
            return ""

        text = str(value).replace("\r\n", "\n").replace("\r", "\n")
        parts = [escape(segment.strip(), quote=False) for segment in text.split("\n")]
        text = "<br>".join(parts)
        return text.replace("\\", "\\\\").replace("|", "\\|")

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
