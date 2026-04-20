"""LaTeX renderer for generated tables."""

from __future__ import annotations

from collections import Counter
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

    _NUMERIC_DTYPES = {"integer", "decimal", "percentage", "fraction"}
    _STRING_HEAVY_DTYPES = {"text_short", "date", "identifier", "alphanumeric_code", "symbolic_mixed"}
    _CATEGORY_DTYPES = {"text_short", "date", "identifier", "alphanumeric_code", "symbolic_mixed"}
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

        chart = self._select_chart(table, template_name)
        metrics = self._summary_metrics(table, chart)
        preview_table = self._preview_table(table)
        record_cards = self._record_cards(table)
        detail_sections = self._detail_sections(table, style)
        matrix_sections = self._matrix_sections(table, style) if template_name == "split_matrix.tex.j2" else []
        layout_label = self._TEMPLATE_LABELS.get(template_name, "LaTeX Report")
        insight_lines = self._insight_lines(table, layout_label, chart, len(detail_sections) > 1)
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
        chart: dict[str, object] | None,
        has_sectioned_details: bool,
    ) -> list[str]:
        """Build short overview lines that explain the document composition."""

        lines = [
            f"Layout: {layout_label}.",
            "Page 1 reserves space for the summary, one chart, and one compact traceable preview.",
        ]
        if chart is not None:
            lines.append(f"Chart: derived directly from {chart['source_label_plain']}.")
        else:
            lines.append("Chart: omitted because no stable one-column summary was available.")
        if has_sectioned_details:
            lines.append("Detailed rows move to later pages and are split into smaller sections with repeated Record anchors.")
        else:
            lines.append("Detailed rows move to later pages after the overview page so the PDF stays readable.")
        return [self._escape_latex(line) for line in lines]

    def _select_chart(self, table: GeneratedTable, template_name: str) -> dict[str, object] | None:
        """Choose one compact chart using a deterministic, data-driven rule."""

        if template_name in {"editorial_report.tex.j2", "record_cards.tex.j2", "split_matrix.tex.j2"}:
            preferred_kinds = ("category", "numeric")
        else:
            preferred_kinds = ("numeric", "category")

        for chart_kind in preferred_kinds:
            if chart_kind == "numeric":
                chart = self._numeric_chart(table)
            else:
                chart = self._category_chart(table)
            if chart is not None:
                return chart
        return None

    def _numeric_chart(self, table: GeneratedTable) -> dict[str, object] | None:
        """Build a compact distribution chart from the first suitable numeric column."""

        for column_schema in table.schema.columns:
            if column_schema.dtype not in self._NUMERIC_DTYPES:
                continue
            values = [
                numeric_value
                for numeric_value in (
                    self._numeric_value(row.get(column_schema.name), column_schema.dtype)
                    for row in table.rows
                )
                if numeric_value is not None
            ]
            if len(values) < 4:
                continue

            minimum = min(values)
            maximum = max(values)
            if math.isclose(minimum, maximum):
                bin_labels = [self._chart_label(self._format_numeric(minimum))]
                bin_counts = [len(values)]
            else:
                bin_count = min(5, max(4, math.ceil(math.sqrt(len(values)))))
                width = (maximum - minimum) / bin_count
                bin_counts = [0 for _ in range(bin_count)]
                for value in values:
                    if math.isclose(value, maximum):
                        index = bin_count - 1
                    else:
                        index = min(bin_count - 1, max(0, int((value - minimum) / width)))
                    bin_counts[index] += 1
                bin_labels = [
                    self._chart_label(
                        f"{self._format_numeric(minimum + width * index)} to "
                        f"{self._format_numeric(minimum + width * (index + 1))}"
                    )
                    for index in range(bin_count)
                ]

            points = [
                LatexChartPointView(
                    index=index,
                    label_escaped=self._escape_latex(label),
                    value=float(count),
                    value_label_escaped=self._escape_latex(str(count)),
                )
                for index, (label, count) in enumerate(zip(bin_labels, bin_counts))
            ]
            if not points:
                return None

            return {
                "kind": "numeric",
                "title_escaped": self._escape_latex(f"Distribution of {self._display_name(column_schema.name)}"),
                "subtitle_escaped": self._escape_latex("Counts per value band"),
                "source_label_plain": self._display_name(column_schema.name),
                "source_label_escaped": self._escape_latex(self._display_name(column_schema.name)),
                "x_label_escaped": self._escape_latex("Value band"),
                "y_label_escaped": self._escape_latex("Count"),
                "insight_escaped": self._escape_latex(
                    f"Range: {self._format_numeric(minimum)} to {self._format_numeric(maximum)}"
                ),
                "points": points,
                "y_max": max(2.0, float(max(point.value for point in points) + 1.0)),
            }
        return None

    def _category_chart(self, table: GeneratedTable) -> dict[str, object] | None:
        """Build a compact top-frequency chart from the first repeated categorical column."""

        for column_schema in table.schema.columns:
            if column_schema.dtype not in self._CATEGORY_DTYPES:
                continue
            values = [str(row.get(column_schema.name)).strip() for row in table.rows if row.get(column_schema.name) is not None]
            values = [value for value in values if value]
            if len(values) < 4:
                continue
            counts = Counter(values)
            if len(counts) <= 1 or len(counts) >= len(values):
                continue

            top_values = counts.most_common(5)
            points = [
                LatexChartPointView(
                    index=index,
                    label_escaped=self._escape_latex(self._chart_label(value)),
                    value=float(count),
                    value_label_escaped=self._escape_latex(str(count)),
                )
                for index, (value, count) in enumerate(top_values)
            ]
            return {
                "kind": "category",
                "title_escaped": self._escape_latex(f"Top {self._display_name(column_schema.name)} frequencies"),
                "subtitle_escaped": self._escape_latex("Most frequent observed values"),
                "source_label_plain": self._display_name(column_schema.name),
                "source_label_escaped": self._escape_latex(self._display_name(column_schema.name)),
                "x_label_escaped": self._escape_latex(self._display_name(column_schema.name)),
                "y_label_escaped": self._escape_latex("Count"),
                "insight_escaped": self._escape_latex(
                    f"Highest frequency: {top_values[0][0]} ({top_values[0][1]})"
                ),
                "points": points,
                "y_max": max(2.0, float(max(point.value for point in points) + 1.0)),
            }
        return None

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
