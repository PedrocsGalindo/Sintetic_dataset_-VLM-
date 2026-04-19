"""Markdown renderer for generated tables."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path

from generators.table_generator import GeneratedTable
from styles.style_sampler import TableStyle
from utils.io import write_text_file


@dataclass(frozen=True)
class MarkdownFieldView:
    """Represent one field for alternate markdown layouts."""

    label: str
    value: str
    kind: str


@dataclass(frozen=True)
class MarkdownRecordView:
    """Represent one row repackaged for markdown layouts."""

    record_label: str
    fields: list[MarkdownFieldView]
    line_fields: list[MarkdownFieldView]
    detail_fields: list[MarkdownFieldView]
    text_fields: list[MarkdownFieldView]
    compact_fields: list[MarkdownFieldView]
    narrative: str


class MarkdownRenderer:
    """Render a generated table into multiple markdown layout styles."""

    def render(self, table: GeneratedTable, style: TableStyle | None = None) -> str:
        """Create a Markdown representation."""

        template_name = style.template_name if style else "default_markdown"
        records = self._build_records(table)
        title = f"<!-- style: {style.font_family if style else 'default'} / {style.alignment_profile if style else 'default'} / {template_name} -->"
        rendered_title = self._display_name(table.name)

        if template_name == "markdown_records":
            body = self._render_record_list(table, records)
        elif template_name == "markdown_mixed":
            body = self._render_mixed_layout(table, records)
        elif template_name == "markdown_briefing":
            body = self._render_briefing_layout(table, records)
        else:
            body = self._render_table_layout(table, style)

        return "\n".join([title, f"# {rendered_title}", "", body]).rstrip() + "\n"

    def render_to_file(self, table: GeneratedTable, output_path: Path, style: TableStyle | None = None) -> Path:
        """Write a rendered Markdown file to disk."""

        markdown = self.render(table, style)
        write_text_file(output_path, markdown)
        return output_path

    def _render_table_layout(self, table: GeneratedTable, style: TableStyle | None) -> str:
        """Render the classic GitHub-flavored markdown table."""

        header = "| " + " | ".join(self._display_name(column) for column in table.columns) + " |"
        separator = "| " + " | ".join(self._separator_cells(table, style)) + " |"
        rows = [
            "| " + " | ".join(self._escape_cell(row.get(column)) for column in table.columns) + " |"
            for row in table.rows
        ]
        return "\n".join([header, separator, *rows])

    def _render_record_list(self, table: GeneratedTable, records: list[MarkdownRecordView]) -> str:
        """Render one section per record using bullet lists."""

        lines = [
            "## Dataset Snapshot",
            "",
            f"- Rows: {table.n_rows}",
            f"- Columns: {table.n_cols}",
            f"- Layout: record list",
            "",
            "## Records",
            "",
        ]
        for record in records:
            lines.append(f"### {record.record_label}")
            lines.extend(f"- **{field.label}:** {self._escape_inline(field.value)}" for field in record.fields)
            lines.append("")
        return "\n".join(lines).rstrip()

    def _render_mixed_layout(self, table: GeneratedTable, records: list[MarkdownRecordView]) -> str:
        """Render a more custom markdown layout with inline summaries and detail bullets."""

        lines = [
            "## Overview",
            "",
            f"- Rows: {table.n_rows}",
            f"- Columns: {table.n_cols}",
            "- Layout: mixed summary, detail list, and free text",
            "",
            "## Record Notes",
            "",
        ]
        for record in records:
            summary = " | ".join(
                f"{field.label}: {self._escape_inline(field.value)}"
                for field in record.line_fields
            )
            lines.append(f"### {record.record_label}")
            lines.append("")
            lines.append(f"**Summary:** {summary}")
            lines.append("")
            if record.detail_fields:
                lines.append("Details:")
                lines.extend(
                    f"- **{field.label}:** {self._escape_inline(field.value)}"
                    for field in record.detail_fields
                )
                lines.append("")
            lines.append("Free Text:")
            lines.append(self._wrap_free_text(record.narrative))
            lines.append("")
        return "\n".join(lines).rstrip()

    def _render_briefing_layout(self, table: GeneratedTable, records: list[MarkdownRecordView]) -> str:
        """Render a more narrative markdown document with free text and compact bullets."""

        lines = [
            "## Briefing",
            "",
            "This markdown version turns the CSV-style rows into short document notes so the output is less tabular and more document-like.",
            "",
            "## Highlights",
            "",
        ]
        for record in records[: min(8, len(records))]:
            lines.append(f"### {record.record_label}")
            lines.append(self._wrap_free_text(record.narrative))
            lines.append("")
            if record.compact_fields:
                lines.append("Key Fields:")
                lines.extend(
                    f"- **{field.label}:** {self._escape_inline(field.value)}"
                    for field in record.compact_fields[:4]
                )
                lines.append("")

        lines.append("## Full Index")
        lines.append("")
        for record in records:
            short_summary = "; ".join(
                f"{field.label}: {self._escape_inline(field.value)}"
                for field in record.line_fields[:4]
            )
            lines.append(f"- **{record.record_label}** {short_summary}")
        return "\n".join(lines).rstrip()

    def _build_records(self, table: GeneratedTable) -> list[MarkdownRecordView]:
        """Build markdown-oriented record views from the generated table."""

        fields_by_row: list[MarkdownRecordView] = []
        inline_count = min(6, len(table.columns))

        for row_index, row in enumerate(table.rows, start=1):
            fields: list[MarkdownFieldView] = []
            line_fields: list[MarkdownFieldView] = []
            detail_fields: list[MarkdownFieldView] = []
            text_fields: list[MarkdownFieldView] = []
            compact_fields: list[MarkdownFieldView] = []

            for column_index, column_schema in enumerate(table.schema.columns):
                raw_value = row.get(column_schema.name)
                value = "-" if raw_value is None else str(raw_value)
                field = MarkdownFieldView(
                    label=self._display_name(column_schema.name),
                    value=value,
                    kind=self._kind_for_dtype(column_schema.dtype),
                )
                fields.append(field)
                if column_index < inline_count:
                    line_fields.append(field)
                else:
                    detail_fields.append(field)
                if raw_value is None:
                    continue
                if field.kind in {"long_text", "text"}:
                    text_fields.append(field)
                else:
                    compact_fields.append(field)

            narrative = self._narrative_for(fields, text_fields, compact_fields)
            fields_by_row.append(
                MarkdownRecordView(
                    record_label=f"Record {row_index:03d}",
                    fields=fields,
                    line_fields=line_fields,
                    detail_fields=detail_fields,
                    text_fields=text_fields,
                    compact_fields=compact_fields,
                    narrative=narrative,
                )
            )

        return fields_by_row

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
    def _escape_inline(value: str) -> str:
        """Escape inline markdown-sensitive text for list and prose layouts."""

        escaped = escape(value, quote=False)
        return escaped.replace("\\", "\\\\").replace("\n", " ").strip()

    @staticmethod
    def _kind_for_dtype(dtype: str) -> str:
        """Map schema dtypes into coarse markdown content groups."""

        if dtype == "text_long":
            return "long_text"
        if dtype in {"text_short"}:
            return "text"
        return "compact"

    def _narrative_for(
        self,
        fields: list[MarkdownFieldView],
        text_fields: list[MarkdownFieldView],
        compact_fields: list[MarkdownFieldView],
    ) -> str:
        """Build a short paragraph-like summary for one record."""

        parts = [field.value for field in text_fields[:2] if field.value != "-"]
        parts.extend(f"{field.label.lower()} {field.value}" for field in compact_fields[:3] if field.value != "-")
        if not parts:
            parts = [f"{field.label.lower()} {field.value}" for field in fields[:4] if field.value != "-"]
        sentence = ". ".join(part.rstrip(".") for part in parts if part).strip()
        return sentence + "." if sentence else "No descriptive content available."

    def _wrap_free_text(self, text: str) -> str:
        """Return a paragraph-ready markdown line."""

        return self._escape_inline(text)

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
