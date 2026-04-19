"""Markdown renderer for generated tables."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
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


@dataclass(frozen=True)
class MarkdownLayoutProfile:
    """Describe when Markdown layouts should split dense fields into multiple matrices."""

    split_matrices: bool
    split_after: int
    summary_field_limit: int
    full_index_field_limit: int


class MarkdownRenderer:
    """Render a generated table into multiple markdown layout styles."""

    def render(self, table: GeneratedTable, style: TableStyle | None = None) -> str:
        """Create a Markdown representation."""

        template_name = style.template_name if style else "default_markdown"
        records = self._build_records(table)
        layout_profile = self._layout_profile(table)
        title = self._style_comment(style, template_name)
        rendered_title = self._display_name(table.name)

        if template_name == "markdown_records":
            body = self._render_record_list(table, records, layout_profile)
        elif template_name == "markdown_mixed":
            body = self._render_mixed_layout(table, records, layout_profile)
        elif template_name == "markdown_briefing":
            body = self._render_briefing_layout(table, records, layout_profile)
        else:
            body = self._render_table_layout(table, style, layout_profile)

        return "\n".join([title, f"# {rendered_title}", "", body]).rstrip() + "\n"

    def render_to_file(self, table: GeneratedTable, output_path: Path, style: TableStyle | None = None) -> Path:
        """Write a rendered Markdown file to disk."""

        markdown = self.render(table, style)
        write_text_file(output_path, markdown)
        return output_path

    def _render_table_layout(
        self,
        table: GeneratedTable,
        style: TableStyle | None,
        layout_profile: MarkdownLayoutProfile,
    ) -> str:
        """Render the classic GitHub-flavored markdown table."""

        if layout_profile.split_matrices:
            return self._render_split_table_layout(table, style, layout_profile)

        header = "| " + " | ".join(self._display_name(column) for column in table.columns) + " |"
        separator = "| " + " | ".join(self._separator_cells(table, style)) + " |"
        rows = [
            "| " + " | ".join(self._escape_cell(row.get(column)) for column in table.columns) + " |"
            for row in table.rows
        ]
        return "\n".join([header, separator, *rows])

    def _render_record_list(
        self,
        table: GeneratedTable,
        records: list[MarkdownRecordView],
        layout_profile: MarkdownLayoutProfile,
    ) -> str:
        """Render one section per record using bullet lists."""

        lines = [
            "## Dataset Snapshot",
            "",
            f"- Rows: {table.n_rows}",
            f"- Columns: {table.n_cols}",
            f"- Layout: record list",
            (
                "- Traceability: Record anchors repeat across matrix splits."
                if layout_profile.split_matrices
                else "- Traceability: one block per record."
            ),
            "",
            "## Records",
            "",
        ]
        for record in records:
            lines.append(f"### {record.record_label}")
            lines.append("")
            lines.append(f"> {self._escape_inline(record.narrative)}")
            lines.append("")
            if layout_profile.split_matrices:
                self._append_matrix_groups(
                    lines,
                    record,
                    self._fields_for_split(record),
                    layout_profile,
                )
            else:
                lines.extend(f"- **{field.label}:** {self._escape_inline(field.value)}" for field in record.fields)
                lines.append("")
        return "\n".join(lines).rstrip()

    def _render_mixed_layout(
        self,
        table: GeneratedTable,
        records: list[MarkdownRecordView],
        layout_profile: MarkdownLayoutProfile,
    ) -> str:
        """Render a more custom markdown layout with inline summaries and detail bullets."""

        lines = [
            "## Overview",
            "",
            f"- Rows: {table.n_rows}",
            f"- Columns: {table.n_cols}",
            "- Layout: mixed summary, detail list, and free text",
            (
                "- Traceability: Record anchors are repeated in each matrix when the field set is split."
                if layout_profile.split_matrices
                else "- Traceability: each note stays grouped under one record."
            ),
            "",
            "## Record Notes",
            "",
        ]
        for record in records:
            summary = " | ".join(
                f"{field.label}: {self._escape_inline(field.value)}"
                for field in record.line_fields[: layout_profile.summary_field_limit]
            )
            lines.append(f"### {record.record_label}")
            lines.append("")
            lines.append(f"**Summary:** {summary}")
            lines.append("")
            if layout_profile.split_matrices:
                self._append_matrix_groups(
                    lines,
                    record,
                    self._fields_for_split(record),
                    layout_profile,
                )
            elif record.detail_fields:
                lines.append("Details:")
                lines.extend(
                    f"- **{field.label}:** {self._escape_inline(field.value)}"
                    for field in record.detail_fields
                )
                lines.append("")
            lines.append("Free Text:")
            lines.append(f"> {self._wrap_free_text(record.narrative)}")
            lines.append("")
        return "\n".join(lines).rstrip()

    def _render_briefing_layout(
        self,
        table: GeneratedTable,
        records: list[MarkdownRecordView],
        layout_profile: MarkdownLayoutProfile,
    ) -> str:
        """Render a more narrative markdown document with free text and compact bullets."""

        lines = [
            "## Briefing",
            "",
            "> This markdown version turns the CSV-style rows into short document notes so the output is less tabular and more document-like.",
            "",
            "## Highlights",
            "",
        ]
        for record in records[: min(8, len(records))]:
            lines.append(f"### {record.record_label}")
            lines.append(f"> {self._wrap_free_text(record.narrative)}")
            lines.append("")
            if record.compact_fields:
                if layout_profile.split_matrices:
                    self._append_matrix_groups(lines, record, record.compact_fields, layout_profile)
                else:
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
                for field in record.line_fields[: layout_profile.full_index_field_limit]
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

    def _render_split_table_layout(
        self,
        table: GeneratedTable,
        style: TableStyle | None,
        layout_profile: MarkdownLayoutProfile,
    ) -> str:
        """Render wide string-heavy tables as two anchored matrices instead of one dense table."""

        split_after = min(layout_profile.split_after, len(table.columns) - 1)
        column_groups = [
            ("Matrix A", table.columns[:split_after]),
            ("Matrix B", table.columns[split_after:]),
        ]
        alignment_profile = style.alignment_profile if style else "mixed"
        lines = [
            "## Table Overview",
            "",
            "- Layout: split matrix for string-heavy columns",
            "- Traceability: each matrix repeats the same `Record NNN` anchor for every row.",
            "",
        ]

        for group_label, columns in column_groups:
            if not columns:
                continue
            lines.extend([f"## {group_label}", "", f"_Shared anchor: every row repeats its record label in this matrix._", ""])
            header_cells = ["Record", *[self._display_name(column) for column in columns]]
            separator_cells = [":---"]
            for column_schema in table.schema.columns:
                if column_schema.name in columns:
                    separator_cells.append(self._separator_cell_for_dtype(column_schema.dtype, alignment_profile))
            lines.append("| " + " | ".join(header_cells) + " |")
            lines.append("| " + " | ".join(separator_cells) + " |")
            for row_index, row in enumerate(table.rows, start=1):
                row_cells = [f"Record {row_index:03d}"]
                row_cells.extend(self._escape_cell(row.get(column)) for column in columns)
                lines.append("| " + " | ".join(row_cells) + " |")
            lines.append("")

        return "\n".join(lines).rstrip()

    def _separator_cells(self, table: GeneratedTable, style: TableStyle | None) -> list[str]:
        """Build Markdown alignment cells."""

        alignment_profile = style.alignment_profile if style else "mixed"
        cells: list[str] = []
        for column in table.schema.columns:
            cells.append(self._separator_cell_for_dtype(column.dtype, alignment_profile))
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

    def _layout_profile(self, table: GeneratedTable) -> MarkdownLayoutProfile:
        """Detect when string/category-heavy datasets need split matrices for readability."""

        string_like_dtypes = {"text_short", "date", "identifier", "alphanumeric_code", "symbolic_mixed"}
        compact_string_count = sum(column.dtype in string_like_dtypes for column in table.schema.columns)
        leading_string_count = sum(
            column.dtype in string_like_dtypes
            for column in table.schema.columns[: min(6, len(table.schema.columns))]
        )
        split_matrices = (
            (table.n_cols >= 8 and compact_string_count >= 5)
            or (table.n_cols >= 7 and leading_string_count >= 4)
            or (table.n_cols >= 9 and compact_string_count / max(table.n_cols, 1) >= 0.5)
        )
        split_after = max(3, min(5, (table.n_cols + 1) // 2))
        return MarkdownLayoutProfile(
            split_matrices=split_matrices,
            split_after=split_after,
            summary_field_limit=3 if split_matrices else 6,
            full_index_field_limit=2 if split_matrices else 4,
        )

    def _fields_for_split(self, record: MarkdownRecordView) -> list[MarkdownFieldView]:
        """Return the fields that should be distributed across split matrices."""

        return [field for field in record.fields if field.kind != "long_text"]

    def _append_matrix_groups_legacy(
        self,
        lines: list[str],
        record: MarkdownRecordView,
        fields: list[MarkdownFieldView],
        layout_profile: MarkdownLayoutProfile,
    ) -> None:
        """Append one or two field matrices with repeated record anchors for traceability."""

        for matrix_label, group_fields in self._matrix_groups(record, fields, layout_profile):
            if not group_fields:
                continue
            lines.append(f"#### {matrix_label} · {record.record_label}")
            lines.extend(
                f"- **{field.label}:** {self._escape_inline(field.value)}"
                for field in group_fields
            )
            lines.append("")

    def _matrix_groups(
        self,
        record: MarkdownRecordView,
        fields: list[MarkdownFieldView],
        layout_profile: MarkdownLayoutProfile,
    ) -> list[tuple[str, list[MarkdownFieldView]]]:
        """Split dense field sets into two stable groups while keeping record identity visible."""

        if not layout_profile.split_matrices or len(fields) <= layout_profile.split_after:
            return [("Matrix A", fields)]

        split_after = self._balanced_split_index(fields, layout_profile.split_after)
        return [
            ("Matrix A", fields[:split_after]),
            ("Matrix B", fields[split_after:]),
        ]

    def _balanced_split_index(self, fields: list[MarkdownFieldView], suggested_split_after: int) -> int:
        """Choose a split point that better matches the assembled size of each matrix."""

        if len(fields) <= 2:
            return 1

        min_group_size = 2 if len(fields) >= 4 else 1
        min_index = min_group_size
        max_index = len(fields) - min_group_size
        default_index = max(min_index, min(suggested_split_after, max_index))

        field_weights = [self._field_layout_weight(field) for field in fields]
        total_weight = sum(field_weights)
        running_weight = 0
        best_index = default_index
        best_score: tuple[int, int] | None = None

        for index, weight in enumerate(field_weights[:-1], start=1):
            running_weight += weight
            if index < min_index or index > max_index:
                continue
            left_weight = running_weight
            right_weight = total_weight - running_weight
            balance_penalty = abs(left_weight - right_weight)
            position_penalty = abs(index - default_index) * 6
            candidate_score = (balance_penalty + position_penalty, abs(index - default_index))
            if best_score is None or candidate_score < best_score:
                best_score = candidate_score
                best_index = index

        return best_index

    @staticmethod
    def _field_layout_weight(field: MarkdownFieldView) -> int:
        """Estimate how much vertical space one field will likely consume in a record matrix."""

        value = field.value.strip()
        visible_length = len(value) if value and value != "-" else 1
        line_bonus = value.count("\n") * 12
        kind_weight = 24 if field.kind == "long_text" else 18 if field.kind == "text" else 14
        return kind_weight + len(field.label) + min(visible_length, 90) + line_bonus

    def _append_matrix_groups(
        self,
        lines: list[str],
        record: MarkdownRecordView,
        fields: list[MarkdownFieldView],
        layout_profile: MarkdownLayoutProfile,
    ) -> None:
        """Append one or two field matrices with repeated record anchors for traceability."""

        for matrix_label, group_fields in self._matrix_groups(record, fields, layout_profile):
            if not group_fields:
                continue
            lines.append(f"#### {matrix_label} - {record.record_label}")
            lines.extend(
                f"- **{field.label}:** {self._escape_inline(field.value)}"
                for field in group_fields
            )
            lines.append("")

    @staticmethod
    def _style_comment(style: TableStyle | None, template_name: str) -> str:
        """Embed structured style metadata for the downstream HTML renderer."""

        if style is None:
            payload = {
                "template_name": template_name,
                "font_family": "default",
                "font_size_pt": 11,
                "line_height": 1.4,
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
        else:
            payload = {
                "template_name": template_name,
                "font_family": style.font_family,
                "font_size_pt": style.font_size_pt,
                "line_height": style.line_height,
                "alignment_profile": style.alignment_profile,
                "header_emphasis": style.header_emphasis,
                "border_style": style.border_style,
                "text_color": style.text_color,
                "header_background": style.header_background,
                "border_color": style.border_color,
                "background_color": style.background_color,
                "accent_color": style.accent_color,
                "table_width": style.table_width,
                "zebra_striping": style.zebra_striping,
            }
        return f"<!-- markdown-style: {json.dumps(payload, ensure_ascii=True)} -->"

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

    def _separator_cell_for_dtype(self, dtype: str, alignment_profile: str) -> str:
        """Return one Markdown separator cell for the requested dtype/alignment profile."""

        alignment = self._alignment_for(dtype, alignment_profile)
        if alignment == "right":
            return "---:"
        if alignment == "center":
            return ":---:"
        return ":---"
