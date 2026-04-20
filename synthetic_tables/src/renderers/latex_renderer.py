"""LaTeX renderer for generated tables."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from generators.table_generator import GeneratedTable
from styles.style_sampler import TableStyle
from utils.io import write_text_file


@dataclass(frozen=True)
class LatexColumnView:
    """Represent one LaTeX-facing column configuration."""

    header_escaped: str


@dataclass(frozen=True)
class LatexMetricView:
    """Represent one compact overview metric."""

    label_escaped: str
    value_escaped: str


@dataclass(frozen=True)
class LatexFieldView:
    """Represent one record field inside cards or memo blocks."""

    label_escaped: str
    value_escaped: str


@dataclass(frozen=True)
class LatexRecordCardView:
    """Represent one record preview card."""

    record_label_escaped: str
    summary_escaped: str
    lead_fields: list[LatexFieldView]
    detail_fields: list[LatexFieldView]


@dataclass(frozen=True)
class LatexChartPointView:
    """Represent one compact chart point."""

    index: int
    label_escaped: str
    value: float
    value_label_escaped: str


class LatexRenderer:
    """Render a generated table to a styled LaTeX string."""

    _MAX_ROW_LEVEL_CHART_ROWS = 75
    _MAX_POINTS_PER_CHART = 25
    _CHART_POINT_SPACING = 2.0
    _NUMERIC_DTYPES = {"integer", "decimal", "percentage", "fraction"}
    _STRING_HEAVY_DTYPES = {"text_short", "date", "identifier", "alphanumeric_code", "symbolic_mixed"}
    _SAFE_TEMPLATE_NAMES = {"default_table.tex.j2"}
    _CREATIVE_TEMPLATE_NAMES = {
        "executive_brief.tex.j2",
        "editorial_report.tex.j2",
        "data_memo.tex.j2",
        "record_cards.tex.j2",
        "split_matrix.tex.j2",
    }
    _TEMPLATE_LABELS = {
        "executive_brief.tex.j2": "Executive Brief",
        "editorial_report.tex.j2": "Editorial Report",
        "data_memo.tex.j2": "Data Memo",
        "record_cards.tex.j2": "Record Cards",
        "split_matrix.tex.j2": "Split Matrix",
        "default_table.tex.j2": "Structured Table",
    }

    def __init__(self, template_dir: Path | None = None) -> None:
        resolved_template_dir = template_dir or Path(__file__).resolve().parents[1] / "styles" / "templates" / "latex"
        self.environment = Environment(
            loader=FileSystemLoader(str(resolved_template_dir)),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )

    def render(self, table: GeneratedTable, style: TableStyle) -> str:
        """Create a LaTeX representation of the table."""

        template_name = self._resolve_template_name(table, style)
        render_mode = self._render_mode_for_template(template_name)
        template = self.environment.get_template(template_name)

        column_dtypes = ["anchor", *[column.dtype for column in table.schema.columns]]
        column_kinds = ["compact", *[self._column_kind(column.dtype) for column in table.schema.columns]]
        columns = [
            LatexColumnView(header_escaped="Record"),
            *[
                LatexColumnView(header_escaped=self._escape_latex(self._display_name(column_schema.name)))
                for column_schema in table.schema.columns
            ],
        ]
        rows = [
            [
                self._escape_latex(f"Record {row_index:03d}"),
                *[
                    self._escape_latex("" if row[column_name] is None else str(row[column_name]))
                    for column_name in table.columns
                ],
            ]
            for row_index, row in enumerate(table.rows, start=1)
        ]

        charts = self._select_charts(table, template_name)
        chart = charts[0] if charts else None
        metrics = self._summary_metrics(table, chart)
        preview_table = self._preview_table(table)
        record_cards = self._record_cards(table)
        detail_sections = self._detail_sections(table, style)
        matrix_sections = self._matrix_sections(table, style) if template_name == "split_matrix.tex.j2" else []
        layout_label = self._TEMPLATE_LABELS.get(template_name, "LaTeX Report")
        insight_lines = self._insight_lines(table, layout_label, charts, len(detail_sections) > 1)
        is_landscape = template_name == "split_matrix.tex.j2" or len(column_dtypes) >= 9 or sum(
            kind == "long_text" for kind in column_kinds
        ) >= 3

        latex_options = {
            "template_name": template_name,
            "render_mode": render_mode,
            "layout_label_escaped": self._escape_latex(layout_label),
            "arraystretch": max(1.0, style.line_height),
            "tabcolsep_pt": min(style.padding, 4 if is_landscape else 5),
            "has_horizontal_rules": style.border_style != "minimal",
            "geometry_options": "landscape, margin=0.5in" if is_landscape else "margin=0.65in",
            "is_landscape": is_landscape,
            "title_escaped": self._escape_latex(self._display_name(table.name)),
            "title_comment_escaped": self._escape_latex(self._display_name(table.name)),
            "font_package_block": self._font_package_block(style.font_family),
            "accent_rgb": self._hex_to_rgb(style.accent_color),
            "header_rgb": self._hex_to_rgb(style.header_background),
            "border_rgb": self._hex_to_rgb(style.border_color),
            "text_rgb": self._hex_to_rgb(style.text_color),
            "background_rgb": self._hex_to_rgb(style.background_color),
            "full_index_column_spec": self._column_spec(column_dtypes, style.alignment_profile, column_kinds, style.border_style),
            "full_index_font": self._table_font_command(len(column_dtypes), is_landscape),
            "detail_sections": detail_sections,
        }

        return template.render(
            table={
                "name_escaped": self._escape_latex(table.name),
                "display_name_escaped": self._escape_latex(self._display_name(table.name)),
                "rows": table.n_rows,
                "columns": table.n_cols,
            },
            columns=columns,
            rows=rows,
            metrics=metrics,
            chart=chart,
            charts=charts,
            preview_table=preview_table,
            record_cards=record_cards,
            matrix_sections=matrix_sections,
            insight_lines=insight_lines,
            style=style,
            latex=latex_options,
        )

    def render_to_file(self, table: GeneratedTable, style: TableStyle, output_path: Path) -> Path:
        """Write a rendered LaTeX file to disk."""

        latex = self.render(table, style)
        write_text_file(output_path, latex)
        return output_path

    def _resolve_template_name(self, table: GeneratedTable, style: TableStyle) -> str:
        """Choose the final LaTeX template while keeping safe mode explicit."""

        if style.template_name in self._SAFE_TEMPLATE_NAMES:
            return style.template_name

        if self._should_use_split_matrix(table):
            return "split_matrix.tex.j2"

        return style.template_name

    def _render_mode_for_template(self, template_name: str) -> str:
        """Map templates into the intentional LaTeX render modes."""

        if template_name in self._SAFE_TEMPLATE_NAMES:
            return "safe-preview"
        return "creative"

    def _summary_metrics(self, table: GeneratedTable, chart: dict[str, object] | None) -> list[LatexMetricView]:
        """Build the compact overview metric strip."""

        numeric_count = sum(column.dtype in self._NUMERIC_DTYPES for column in table.schema.columns)
        chart_basis = "None" if chart is None else str(chart["source_label_plain"])
        return [
            LatexMetricView(label_escaped="Rows", value_escaped=self._escape_latex(str(table.n_rows))),
            LatexMetricView(label_escaped="Columns", value_escaped=self._escape_latex(str(table.n_cols))),
            LatexMetricView(label_escaped="Numeric", value_escaped=self._escape_latex(str(numeric_count))),
            LatexMetricView(label_escaped="Chart", value_escaped=self._escape_latex(chart_basis)),
        ]

    def _record_cards(self, table: GeneratedTable, limit: int = 6) -> list[LatexRecordCardView]:
        """Build preview cards that preserve record identity while keeping the layout compact."""

        cards: list[LatexRecordCardView] = []
        for row_index, row in enumerate(table.rows[: min(limit, len(table.rows))], start=1):
            field_views: list[LatexFieldView] = []
            for column_schema in table.schema.columns[: min(8, len(table.schema.columns))]:
                raw_value = row.get(column_schema.name)
                value = "-" if raw_value is None else str(raw_value)
                field_views.append(
                    LatexFieldView(
                        label_escaped=self._escape_latex(self._display_name(column_schema.name)),
                        value_escaped=self._escape_latex(value),
                    )
                )

            summary = self._record_summary(row, table)
            cards.append(
                LatexRecordCardView(
                    record_label_escaped=self._escape_latex(f"Record {row_index:03d}"),
                    summary_escaped=self._escape_latex(summary),
                    lead_fields=field_views[:4],
                    detail_fields=field_views[4:8],
                )
            )
        return cards

    def _record_summary(self, row: dict[str, object], table: GeneratedTable) -> str:
        """Create one concise summary line for a record card."""

        text_candidates: list[str] = []
        compact_candidates: list[str] = []
        for column_schema in table.schema.columns:
            raw_value = row.get(column_schema.name)
            if raw_value is None:
                continue
            value = str(raw_value).strip()
            if not value:
                continue
            if self._column_kind(column_schema.dtype) in {"text", "long_text"}:
                text_candidates.append(value)
            else:
                compact_candidates.append(f"{self._display_name(column_schema.name)} {value}")

        if text_candidates:
            return self._truncate_text(text_candidates[0], 120)
        if compact_candidates:
            return self._truncate_text(". ".join(compact_candidates[:2]), 120)
        return "No descriptive content available."

    def _preview_table(self, table: GeneratedTable) -> dict[str, object] | None:
        """Build a very small first-page table preview with stable record anchors."""

        if not table.rows or not table.schema.columns:
            return None

        data_column_limit = min(table.n_cols, 4 if table.n_cols <= 4 else 3)
        preview_columns = list(table.schema.columns[:data_column_limit])
        preview_headers = ["Record"] + [self._display_name(column.name) for column in preview_columns]
        preview_rows = [
            [
                self._escape_latex(f"Record {row_index:03d}"),
                *[
                    self._escape_latex("" if row.get(column.name) is None else str(row.get(column.name)))
                    for column in preview_columns
                ],
            ]
            for row_index, row in enumerate(table.rows[: min(4, len(table.rows))], start=1)
        ]
        preview_column_spec = " ".join(
            [
                r">{\raggedright\arraybackslash}p{0.18\linewidth}",
                *[r">{\raggedright\arraybackslash}X" for _ in preview_columns],
            ]
        )

        return {
            "title_escaped": self._escape_latex("Traceable Preview"),
            "subtitle_escaped": self._escape_latex(
                "A compact sample of leading fields. The detailed row index continues on later pages."
            ),
            "headers": [self._escape_latex(header) for header in preview_headers],
            "rows": preview_rows,
            "column_spec": preview_column_spec,
        }

    def _detail_sections(self, table: GeneratedTable, style: TableStyle) -> list[dict[str, object]]:
        """Build readable later-page detail tables while repeating the Record anchor."""

        if not table.schema.columns:
            return []

        data_columns_per_section = self._detail_section_column_limit(table)
        if table.n_cols <= data_columns_per_section:
            column_groups = [list(table.schema.columns)]
        else:
            column_groups = [
                list(table.schema.columns[start : start + data_columns_per_section])
                for start in range(0, table.n_cols, data_columns_per_section)
            ]

        sections: list[dict[str, object]] = []
        for section_index, columns in enumerate(column_groups, start=1):
            section_columns = [LatexColumnView(header_escaped="Record")] + [
                LatexColumnView(header_escaped=self._escape_latex(self._display_name(column.name)))
                for column in columns
            ]
            section_rows = [
                [
                    self._escape_latex(f"Record {row_index:03d}"),
                    *[
                        self._escape_latex("" if row.get(column.name) is None else str(row.get(column.name)))
                        for column in columns
                    ],
                ]
                for row_index, row in enumerate(table.rows, start=1)
            ]
            section_dtypes = ["anchor", *[column.dtype for column in columns]]
            section_kinds = ["compact", *[self._column_kind(column.dtype) for column in columns]]
            if len(column_groups) == 1:
                title = "Full Index"
                subtitle = "All columns remain together because the table still fits as one readable detailed section."
            else:
                first_label = self._display_name(columns[0].name)
                last_label = self._display_name(columns[-1].name)
                title = f"Detail Section {section_index}"
                subtitle = (
                    f"Columns from {first_label} through {last_label}. "
                    "Each section repeats the Record anchor so rows remain traceable."
                )
            sections.append(
                {
                    "title_escaped": self._escape_latex(title),
                    "subtitle_escaped": self._escape_latex(subtitle),
                    "columns": section_columns,
                    "rows": section_rows,
                    "column_spec": self._column_spec(
                        section_dtypes,
                        style.alignment_profile,
                        section_kinds,
                        style.border_style,
                    ),
                    "font_command": self._table_font_command(len(section_dtypes), False),
                }
            )
        return sections

    def _detail_section_column_limit(self, table: GeneratedTable) -> int:
        """Choose a deterministic number of data columns per readable detail section."""

        long_text_columns = sum(self._column_kind(column.dtype) == "long_text" for column in table.schema.columns)
        if table.n_cols >= 11 or long_text_columns >= 3:
            return 3
        if table.n_cols >= 5:
            return 4
        return max(1, table.n_cols)

    def _matrix_sections(self, table: GeneratedTable, style: TableStyle) -> list[dict[str, object]]:
        """Build split-matrix sections for wide categorical layouts."""

        split_after = self._balanced_column_split_index(table)
        column_groups = [
            ("Matrix A", table.schema.columns[:split_after]),
            ("Matrix B", table.schema.columns[split_after:]),
        ]
        sections: list[dict[str, object]] = []
        for title, columns in column_groups:
            if not columns:
                continue
            section_columns = [LatexColumnView(header_escaped="Record")] + [
                LatexColumnView(header_escaped=self._escape_latex(self._display_name(column.name)))
                for column in columns
            ]
            section_rows = [
                [
                    self._escape_latex(f"Record {row_index:03d}"),
                    *[
                        self._escape_latex("" if row.get(column.name) is None else str(row.get(column.name)))
                        for column in columns
                    ],
                ]
                for row_index, row in enumerate(table.rows, start=1)
            ]
            section_dtypes = ["anchor", *[column.dtype for column in columns]]
            section_kinds = ["compact", *[self._column_kind(column.dtype) for column in columns]]
            sections.append(
                {
                    "title_escaped": self._escape_latex(title),
                    "subtitle_escaped": self._escape_latex(
                        "Each section repeats the same Record anchor so both matrices map directly to the source rows."
                    ),
                    "columns": section_columns,
                    "rows": section_rows,
                    "column_spec": self._column_spec(
                        section_dtypes,
                        style.alignment_profile,
                        section_kinds,
                        style.border_style,
                    ),
                }
            )
        return sections

    def _balanced_column_split_index(self, table: GeneratedTable) -> int:
        """Choose a stable split point for wide datasets based on assembled column pressure."""

        if table.n_cols <= 4:
            return max(1, table.n_cols // 2)

        weights = [
            self._column_layout_weight(column.name, self._column_kind(column.dtype))
            for column in table.schema.columns
        ]
        total_weight = sum(weights)
        running_weight = 0.0
        min_index = 3 if table.n_cols >= 6 else 2
        max_index = max(min_index, table.n_cols - 2)
        default_index = max(min_index, min((table.n_cols + 1) // 2, max_index))
        best_index = default_index
        best_score: tuple[float, int] | None = None

        for index, weight in enumerate(weights[:-1], start=1):
            running_weight += weight
            if index < min_index or index > max_index:
                continue
            left_weight = running_weight
            right_weight = total_weight - running_weight
            score = (abs(left_weight - right_weight) + abs(index - default_index) * 0.65, abs(index - default_index))
            if best_score is None or score < best_score:
                best_score = score
                best_index = index

        return best_index

    def _column_layout_weight(self, name: str, kind: str) -> float:
        """Estimate how visually heavy one column will be in a split matrix."""

        base = {
            "long_text": 2.2,
            "text": 1.25,
            "compact": 0.85,
        }.get(kind, 1.0)
        return base + min(len(name), 24) * 0.035

    def _insight_lines(
        self,
        table: GeneratedTable,
        layout_label: str,
        charts: list[dict[str, object]],
        has_sectioned_details: bool,
    ) -> list[str]:
        """Build short overview lines that explain the document composition."""

        lines = [
            f"Layout: {layout_label}.",
            "Page 1 reserves space for the summary, full-width chart blocks, and one compact traceable preview.",
        ]
        if charts:
            primary_chart = charts[0]
            lines.append(f"Chart: derived directly from {primary_chart['source_label_plain']}.")
            lines.append("Chart blocks use the full page width so row-level labels stay readable.")
            if len(charts) > 1:
                lines.append(
                    f"Chart split: the row-level series is split into {len(charts)} full-width panels with at most "
                    f"{self._MAX_POINTS_PER_CHART} rows each."
                )
        else:
            if table.n_rows > self._MAX_ROW_LEVEL_CHART_ROWS:
                lines.append("Chart: omitted because row-level LaTeX charts are limited to datasets with at most 75 rows.")
            else:
                lines.append("Chart: omitted because no stable one-column summary was available.")
        if has_sectioned_details:
            lines.append("Detailed rows move to later pages and are split into smaller sections with repeated Record anchors.")
        else:
            lines.append("Detailed rows move to later pages after the overview page so the PDF stays readable.")
        return [self._escape_latex(line) for line in lines]

    def _select_charts(self, table: GeneratedTable, template_name: str) -> list[dict[str, object]]:
        """Choose row-level LaTeX charts using deterministic, readability-first rules."""

        _ = template_name
        if table.n_rows > self._MAX_ROW_LEVEL_CHART_ROWS:
            return []
        return self._row_level_numeric_charts(table)

    def _row_level_numeric_charts(self, table: GeneratedTable) -> list[dict[str, object]]:
        """Plot one numeric column directly against a traceable row-level x-axis."""

        for column_schema in table.schema.columns:
            if column_schema.dtype not in self._NUMERIC_DTYPES:
                continue

            numeric_rows: list[dict[str, object]] = []
            for row_index, row in enumerate(table.rows, start=1):
                numeric_value = self._numeric_value(row.get(column_schema.name), column_schema.dtype)
                if numeric_value is None:
                    continue
                numeric_rows.append(
                    {
                        "row_index": row_index,
                        "row": row,
                        "numeric_value": numeric_value,
                    }
                )

            if len(numeric_rows) < 4:
                continue

            x_axis = self._chart_x_axis(table, numeric_rows)
            values = [float(point["numeric_value"]) for point in numeric_rows]
            minimum = min(values)
            maximum = max(values)

            y_padding = max(1.0, abs(maximum) * 0.12)
            y_min = min(0.0, minimum - y_padding)
            y_max = max(2.0, maximum + y_padding)
            chart_chunks = [
                x_axis["points"][start : start + self._MAX_POINTS_PER_CHART]
                for start in range(0, len(x_axis["points"]), self._MAX_POINTS_PER_CHART)
            ]
            charts: list[dict[str, object]] = []
            for chunk_index, chart_chunk in enumerate(chart_chunks, start=1):
                points = [
                    LatexChartPointView(
                        index=float(
                            self._chart_point_index(
                                raw_index_label=str(point["index_label"]),
                                fallback_row_index=int(point["row_index"]),
                            )
                        ),
                        label_escaped=self._escape_latex(self._chart_label(str(point["label"]))),
                        value=float(point["numeric_value"]),
                        value_label_escaped=self._escape_latex(self._format_numeric(float(point["numeric_value"]))),
                    )
                    for point in chart_chunk
                ]
                if not points:
                    continue
                title_plain = f"{self._display_name(column_schema.name)} by {x_axis['axis_label_plain']}"
                if len(chart_chunks) > 1:
                    chunk_start = 1 + (chunk_index - 1) * self._MAX_POINTS_PER_CHART
                    chunk_end = chunk_start + len(points) - 1
                    title_plain = f"{title_plain} (Rows {chunk_start}-{chunk_end})"
                charts.append(
                    {
                        "kind": "row-level-numeric",
                        "title_escaped": self._escape_latex(title_plain),
                        "subtitle_escaped": self._escape_latex(
                            f"Direct row-level values from {len(points)} source rows"
                        ),
                        "source_label_plain": self._display_name(column_schema.name),
                        "source_label_escaped": self._escape_latex(
                            f"{self._display_name(column_schema.name)} vs {x_axis['axis_label_plain']}"
                        ),
                        "x_label_escaped": self._escape_latex(x_axis["axis_label_plain"]),
                        "y_label_escaped": self._escape_latex(self._display_name(column_schema.name)),
                        "insight_escaped": self._escape_latex(
                            f"{x_axis['insight_plain']} Range: {self._format_numeric(minimum)} to {self._format_numeric(maximum)}."
                        ),
                        "points": points,
                        "y_min": y_min,
                        "y_max": y_max,
                        "x_max": max(point.index for point in points) + 1.0,
                    }
                )
            return charts
        return []

    def _chart_x_axis(
        self,
        table: GeneratedTable,
        numeric_rows: list[dict[str, object]],
    ) -> dict[str, object]:
        """Choose a traceable row-level x-axis for the LaTeX chart."""

        for column_schema in table.schema.columns:
            if column_schema.dtype != "date":
                continue
            labels = self._axis_labels_for_column(numeric_rows, column_schema.name)
            if labels is None:
                continue
            return {
                "axis_label_plain": self._display_name(column_schema.name),
                "points": labels,
                "insight_plain": (
                    f"Unique dates on the x-axis preserve direct row traceability for each source row."
                ),
            }

        for column_schema in table.schema.columns:
            if column_schema.dtype not in {"identifier", "alphanumeric_code"}:
                continue
            labels = self._axis_labels_for_column(numeric_rows, column_schema.name)
            if labels is None:
                continue
            return {
                "axis_label_plain": self._display_name(column_schema.name),
                "points": labels,
                "insight_plain": (
                    "Repeated dates prevented a date x-axis, so the chart uses a stable record identifier instead."
                ),
            }

        return {
            "axis_label_plain": "Record",
            "points": [
                {
                    "label": f"{int(point['row_index']):03d}",
                    "index_label": f"{int(point['row_index']):03d}",
                    "row_index": int(point["row_index"]),
                    "numeric_value": float(point["numeric_value"]),
                }
                for point in numeric_rows
            ],
            "insight_plain": (
                "Repeated or unavailable dates prevented a unique date axis, so the chart uses explicit row indices."
            ),
        }

    def _axis_labels_for_column(
        self,
        numeric_rows: list[dict[str, object]],
        column_name: str,
    ) -> list[dict[str, object]] | None:
        """Return row-aligned labels when one candidate x-axis column is complete and unique."""

        labels: list[dict[str, object]] = []
        seen_labels: set[str] = set()
        for point in numeric_rows:
            raw_label = point["row"].get(column_name)
            if raw_label is None:
                return None
            label = str(raw_label).strip()
            if not label or label in seen_labels:
                return None
            seen_labels.add(label)
            labels.append(
                {
                    "label": label,
                    "index_label": label,
                    "row_index": int(point["row_index"]),
                    "numeric_value": float(point["numeric_value"]),
                }
            )
        return labels

    @staticmethod
    def _chart_point_index(raw_index_label: str, fallback_row_index: int) -> int:
        """Convert one chart index token into a numeric-only deterministic LaTeX x position."""

        digit_groups = [chunk for chunk in "".join(ch if ch.isdigit() else " " for ch in raw_index_label).split() if chunk]
        if digit_groups:
            numeric_index = int(digit_groups[-1])
        else:
            numeric_index = int(fallback_row_index)
        if numeric_index <= 0:
            numeric_index = int(fallback_row_index)
        return min(numeric_index, 999)

    def _should_use_split_matrix(self, table: GeneratedTable) -> bool:
        """Detect when wide categorical layouts need a split-matrix presentation."""

        compact_string_count = sum(column.dtype in self._STRING_HEAVY_DTYPES for column in table.schema.columns)
        leading_string_count = sum(
            column.dtype in self._STRING_HEAVY_DTYPES for column in table.schema.columns[: min(6, len(table.schema.columns))]
        )
        return (
            (table.n_cols >= 8 and compact_string_count >= 5)
            or (table.n_cols >= 7 and leading_string_count >= 4)
            or (table.n_cols >= 9 and compact_string_count / max(table.n_cols, 1) >= 0.5)
        )

    def _column_spec(
        self,
        dtypes: list[str],
        alignment_profile: str,
        column_kinds: list[str],
        border_style: str,
    ) -> str:
        """Build the column specification for one LaTeX table."""

        separator = " " if border_style == "minimal" else " "
        width_fractions = self._column_width_fractions(column_kinds)
        tokens = [
            self._alignment_token(dtype, alignment_profile, width_fractions[index])
            for index, dtype in enumerate(dtypes)
        ]
        body = separator.join(tokens)
        if border_style == "minimal":
            return body
        return body

    @staticmethod
    def _alignment_token(dtype: str, alignment_profile: str, width_fraction: float) -> str:
        width = f"{width_fraction:.3f}\\linewidth"
        if dtype == "anchor":
            return rf">{{\raggedright\arraybackslash}}p{{{width}}}"
        if alignment_profile == "left":
            return rf">{{\raggedright\arraybackslash}}p{{{width}}}"
        if alignment_profile == "center":
            return rf">{{\centering\arraybackslash}}p{{{width}}}"
        if alignment_profile == "numeric_right":
            if dtype in {"integer", "decimal", "percentage", "fraction"}:
                return rf">{{\raggedleft\arraybackslash}}p{{{width}}}"
            return rf">{{\raggedright\arraybackslash}}p{{{width}}}"
        if dtype in {"integer", "decimal", "percentage", "fraction"}:
            return rf">{{\raggedleft\arraybackslash}}p{{{width}}}"
        if dtype in {"date", "identifier", "alphanumeric_code", "symbolic_mixed"}:
            return rf">{{\centering\arraybackslash}}p{{{width}}}"
        return rf">{{\raggedright\arraybackslash}}p{{{width}}}"

    @staticmethod
    def _column_kind(dtype: str) -> str:
        if dtype == "text_long":
            return "long_text"
        if dtype in {"integer", "decimal", "percentage", "fraction", "date", "identifier", "alphanumeric_code", "symbolic_mixed"}:
            return "compact"
        return "text"

    @staticmethod
    def _column_width_fractions(column_kinds: list[str]) -> list[float]:
        """Allocate line width to descriptive columns while keeping compact fields narrower."""

        weight_map = {
            "long_text": 1.9,
            "text": 1.1,
            "compact": 0.78,
        }
        weights = [weight_map.get(kind, 1.0) for kind in column_kinds]
        total_weight = sum(weights) or float(len(column_kinds))
        target_total = 0.95 if len(column_kinds) >= 10 else 0.97 if len(column_kinds) >= 7 else 0.99
        return [(weight / total_weight) * target_total for weight in weights]

    @staticmethod
    def _font_package_block(font_family: str) -> str:
        """Map the sampled LaTeX font family to a stable package block."""

        normalized = font_family.strip().lower()
        if normalized == "ptm":
            return "\\usepackage{mathptmx}"
        if normalized == "phv":
            return "\\usepackage[scaled=0.94]{helvet}\n\\renewcommand{\\familydefault}{\\sfdefault}"
        if normalized == "ppl":
            return "\\usepackage{mathpazo}"
        return "\\usepackage{lmodern}"

    @staticmethod
    def _table_font_command(column_count: int, is_landscape: bool) -> str:
        """Choose a safe table font size for the full index section."""

        if column_count >= 10:
            return "\\scriptsize"
        if column_count >= 8 or is_landscape:
            return "\\footnotesize"
        return "\\small"

    @staticmethod
    def _display_name(value: str) -> str:
        """Convert internal slugs into reader-friendly labels."""

        return value.replace("_", " ").title()

    @staticmethod
    def _truncate_text(value: str, limit: int) -> str:
        """Shorten long text for compact hero and card surfaces."""

        collapsed = " ".join(value.split())
        if len(collapsed) <= limit:
            return collapsed
        return collapsed[: max(0, limit - 3)].rstrip() + "..."

    @staticmethod
    def _chart_label(value: str, limit: int = 18) -> str:
        """Normalize chart labels so pgfplots stays stable."""

        collapsed = " ".join(value.replace(",", " ").split())
        if len(collapsed) <= limit:
            return collapsed
        return collapsed[: max(0, limit - 3)].rstrip() + "..."

    @staticmethod
    def _format_numeric(value: float) -> str:
        """Format a numeric value for labels and chart notes."""

        if math.isclose(value, round(value), abs_tol=1e-9):
            return str(int(round(value)))
        if abs(value) >= 100:
            return f"{value:.1f}"
        if abs(value) >= 10:
            return f"{value:.2f}"
        return f"{value:.3f}".rstrip("0").rstrip(".")

    def _numeric_value(self, raw_value: object, dtype: str) -> float | None:
        """Convert one generated cell into a numeric chart value when possible."""

        if raw_value is None:
            return None
        if isinstance(raw_value, (int, float)):
            return float(raw_value)

        text = str(raw_value).strip().replace(",", "")
        if not text:
            return None
        if dtype == "percentage" and text.endswith("%"):
            text = text[:-1]
        if dtype == "fraction" and "/" in text:
            numerator, denominator = text.split("/", 1)
            try:
                denominator_value = float(denominator)
                if math.isclose(denominator_value, 0.0):
                    return None
                return float(numerator) / denominator_value
            except ValueError:
                return None
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _hex_to_rgb(hex_value: str) -> str:
        """Convert one hex color into an RGB triple for xcolor."""

        normalized = hex_value.strip().lstrip("#")
        if len(normalized) != 6:
            return "44,82,130"
        red = int(normalized[0:2], 16)
        green = int(normalized[2:4], 16)
        blue = int(normalized[4:6], 16)
        return f"{red},{green},{blue}"

    @staticmethod
    def _escape_latex(value: str) -> str:
        replacements = {
            "\\": r"\textbackslash{}",
            "&": r"\&",
            "%": r"\%",
            "$": r"\$",
            "#": r"\#",
            "_": r"\_",
            "{": r"\{",
            "}": r"\}",
            "~": r"\textasciitilde{}",
            "^": r"\textasciicircum{}",
        }
        escaped = value
        for original, replacement in replacements.items():
            escaped = escaped.replace(original, replacement)
        return escaped
