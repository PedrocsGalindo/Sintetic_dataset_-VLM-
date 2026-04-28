"""LaTeX renderer for generated tables."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from generators.schema_generator import ColumnSchema
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
    index_label_escaped: str
    plot_position: float
    label_escaped: str
    value: float
    value_label_escaped: str


@dataclass(frozen=True)
class LatexLayoutSettings:
    """Describe one candidate LaTeX fit mode."""

    name: str
    is_landscape: bool
    max_visible_columns: int
    tabcolsep_pt: float
    font_command: str
    target_width_fraction: float
    max_pressure: float


@dataclass(frozen=True)
class LatexTableLayoutPlan:
    """Centralized layout decision for one rendered LaTeX table."""

    strategy: str
    is_landscape: bool
    geometry_options: str
    tabcolsep_pt: float
    arraystretch: float
    full_index_column_spec: str
    full_index_font: str
    detail_sections: list[dict[str, object]]


class LatexRenderer:
    """Render a generated table to a styled LaTeX string."""

    _MAX_ROW_LEVEL_CHART_ROWS = 75
    _MAX_POINTS_PER_CHART = 25
    _CHART_POINT_SPACING = 2.0
    _MAX_VISIBLE_COLUMNS_PER_BLOCK = 7
    _MAX_VISIBLE_COLUMNS_PORTRAIT = _MAX_VISIBLE_COLUMNS_PER_BLOCK
    _MAX_VISIBLE_COLUMNS_LANDSCAPE = _MAX_VISIBLE_COLUMNS_PER_BLOCK
    _MAX_VISIBLE_COLUMNS_SPLIT_BLOCK = _MAX_VISIBLE_COLUMNS_PER_BLOCK
    _MIN_TABCOLSEP_PT = 2.5
    _LONG_TEXT_MAX_VISUAL_LINES = 3
    _LONG_TEXT_MIN_CHARS_PER_LINE = 16
    _LONG_TEXT_WRAP_THRESHOLD = 30
    _LONG_TEXT_TRUNCATION_SUFFIX = r"\ldots{}"
    _NUMERIC_DTYPES = {"integer", "decimal", "percentage", "fraction"}
    _STRING_HEAVY_DTYPES = {"text_short", "date", "identifier", "alphanumeric_code", "symbolic_mixed"}
    _SIMPLE_TEMPLATE_NAMES = {"simple_tabular.tex.j2"}
    _SAFE_TEMPLATE_NAMES = {"default_table.tex.j2"}
    _CREATIVE_TEMPLATE_NAMES = {
        "simple_tabular.tex.j2",
        "executive_brief.tex.j2",
        "editorial_report.tex.j2",
        "data_memo.tex.j2",
        "record_cards.tex.j2",
        "split_matrix.tex.j2",
    }
    _TEMPLATE_LABELS = {
        "simple_tabular.tex.j2": "Simple Tabular",
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

        layout_plan = self._plan_table_layout(table, style, column_dtypes, column_kinds)

        is_simple_template = template_name in self._SIMPLE_TEMPLATE_NAMES
        if is_simple_template:
            charts: list[dict[str, object]] = []
            chart = None
            metrics: list[LatexMetricView] = []
            preview_table = None
            record_cards: list[LatexRecordCardView] = []
            detail_sections = layout_plan.detail_sections
            matrix_sections: list[dict[str, object]] = []
            layout_label = self._TEMPLATE_LABELS.get(template_name, "LaTeX Report")
            insight_lines: list[str] = []
        else:
            charts = self._select_charts(table, template_name)
            chart = charts[0] if charts else None
            metrics = self._summary_metrics(table, chart)
            preview_table = self._preview_table(table, layout_plan)
            record_cards = self._record_cards(table)
            detail_sections = layout_plan.detail_sections
            matrix_sections = self._matrix_sections(table, style) if template_name == "split_matrix.tex.j2" else []
            layout_label = self._TEMPLATE_LABELS.get(template_name, "LaTeX Report")
            insight_lines = self._insight_lines(table, layout_label, charts, len(detail_sections) > 1)

        latex_options = {
            "template_name": template_name,
            "render_mode": render_mode,
            "layout_label_escaped": self._escape_latex(layout_label),
            "layout_strategy": layout_plan.strategy,
            "layout_strategy_escaped": self._escape_latex(layout_plan.strategy.replace("-", " ")),
            "arraystretch": layout_plan.arraystretch,
            "tabcolsep_pt": layout_plan.tabcolsep_pt,
            "has_horizontal_rules": style.border_style != "minimal",
            "geometry_options": layout_plan.geometry_options,
            "is_landscape": layout_plan.is_landscape,
            "title_escaped": self._escape_latex(self._display_name(table.name)),
            "title_comment_escaped": self._escape_latex(self._display_name(table.name)),
            "font_package_block": self._font_package_block(style.font_family),
            "accent_rgb": self._hex_to_rgb(style.accent_color),
            "header_rgb": self._hex_to_rgb(style.header_background),
            "border_rgb": self._hex_to_rgb(style.border_color),
            "text_rgb": self._hex_to_rgb(style.text_color),
            "background_rgb": self._hex_to_rgb(style.background_color),
            "full_index_column_spec": layout_plan.full_index_column_spec,
            "full_index_font": layout_plan.full_index_font,
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

        if style.template_name in self._SIMPLE_TEMPLATE_NAMES:
            return style.template_name

        if style.template_name in self._SAFE_TEMPLATE_NAMES:
            return style.template_name

        if self._should_use_split_matrix(table):
            return "split_matrix.tex.j2"

        return style.template_name

    def _render_mode_for_template(self, template_name: str) -> str:
        """Map templates into the intentional LaTeX render modes."""

        if template_name in self._SIMPLE_TEMPLATE_NAMES:
            return "simple-tabular"
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

    def _preview_table(self, table: GeneratedTable, layout_plan: LatexTableLayoutPlan) -> dict[str, object] | None:
        """Build a very small first-page table preview with stable record anchors."""

        if not table.rows or not table.schema.columns:
            return None

        data_column_limit = min(table.n_cols, 4 if table.n_cols <= 4 else 3)
        preview_columns = list(table.schema.columns[:data_column_limit])
        preview_data_width = 0.82 / max(1, len(preview_columns))
        preview_headers = ["Record"] + [self._display_name(column.name) for column in preview_columns]
        preview_rows = [
            [
                self._escape_latex(f"Record {row_index:03d}"),
                *[
                    self._format_latex_cell_value(
                        raw_value=row.get(column.name),
                        column=column,
                        width_fraction=preview_data_width,
                        is_landscape=layout_plan.is_landscape,
                        font_command="\\footnotesize",
                        tabcolsep_pt=layout_plan.tabcolsep_pt,
                    )
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

    def _plan_table_layout(
        self,
        table: GeneratedTable,
        style: TableStyle,
        column_dtypes: list[str],
        column_kinds: list[str],
    ) -> LatexTableLayoutPlan:
        """Plan orientation, compactness, widths, and horizontal splits for one LaTeX table."""

        if not table.schema.columns:
            layout = self._layout_settings("portrait", style)
            return LatexTableLayoutPlan(
                strategy=layout.name,
                is_landscape=layout.is_landscape,
                geometry_options=self._geometry_options(layout),
                tabcolsep_pt=layout.tabcolsep_pt,
                arraystretch=self._arraystretch_for_layout(style, layout),
                full_index_column_spec=self._column_spec(
                    column_dtypes,
                    style.alignment_profile,
                    column_kinds,
                    style.border_style,
                    width_fractions=[0.98],
                ),
                full_index_font=layout.font_command,
                detail_sections=[],
            )

        for layout in self._layout_candidates(style):
            if self._columns_fit_layout(table, list(table.schema.columns), layout):
                column_groups = [list(table.schema.columns)]
                return self._layout_plan_from_groups(
                    table=table,
                    style=style,
                    column_dtypes=column_dtypes,
                    column_kinds=column_kinds,
                    column_groups=column_groups,
                    layout=layout,
                )

        split_layout = self._layout_settings("split", style)
        column_groups = self._partition_columns_for_layout(table, split_layout)
        return self._layout_plan_from_groups(
            table=table,
            style=style,
            column_dtypes=column_dtypes,
            column_kinds=column_kinds,
            column_groups=column_groups,
            layout=split_layout,
        )

    def _layout_plan_from_groups(
        self,
        table: GeneratedTable,
        style: TableStyle,
        column_dtypes: list[str],
        column_kinds: list[str],
        column_groups: list[list[ColumnSchema]],
        layout: LatexLayoutSettings,
    ) -> LatexTableLayoutPlan:
        """Materialize the selected layout settings into template-ready sections."""

        full_width_fractions = self._section_width_fractions(table, list(table.schema.columns), layout)
        return LatexTableLayoutPlan(
            strategy=layout.name,
            is_landscape=layout.is_landscape,
            geometry_options=self._geometry_options(layout),
            tabcolsep_pt=layout.tabcolsep_pt,
            arraystretch=self._arraystretch_for_layout(style, layout),
            full_index_column_spec=self._column_spec(
                column_dtypes,
                style.alignment_profile,
                column_kinds,
                style.border_style,
                width_fractions=full_width_fractions,
            ),
            full_index_font=layout.font_command,
            detail_sections=self._detail_sections(
                table=table,
                style=style,
                column_groups=column_groups,
                layout=layout,
            ),
        )

    def _layout_candidates(self, style: TableStyle) -> list[LatexLayoutSettings]:
        """Return the ordered fit attempts before mandatory column splitting."""

        return [
            self._layout_settings("portrait", style),
            self._layout_settings("landscape", style),
            self._layout_settings("landscape-compact", style),
        ]

    def _layout_settings(self, name: str, style: TableStyle) -> LatexLayoutSettings:
        """Build one concrete LaTeX fit mode."""

        if name == "portrait":
            return LatexLayoutSettings(
                name=name,
                is_landscape=False,
                max_visible_columns=self._MAX_VISIBLE_COLUMNS_PORTRAIT,
                tabcolsep_pt=max(self._MIN_TABCOLSEP_PT, min(float(style.padding), 5.0)),
                font_command="\\small",
                target_width_fraction=0.98,
                max_pressure=0.30,
            )
        if name == "landscape":
            return LatexLayoutSettings(
                name=name,
                is_landscape=True,
                max_visible_columns=self._MAX_VISIBLE_COLUMNS_LANDSCAPE,
                tabcolsep_pt=max(self._MIN_TABCOLSEP_PT, min(float(style.padding), 4.0)),
                font_command="\\footnotesize",
                target_width_fraction=0.98,
                max_pressure=0.26,
            )
        if name == "landscape-compact":
            return LatexLayoutSettings(
                name=name,
                is_landscape=True,
                max_visible_columns=self._MAX_VISIBLE_COLUMNS_LANDSCAPE,
                tabcolsep_pt=self._MIN_TABCOLSEP_PT,
                font_command="\\scriptsize",
                target_width_fraction=0.98,
                max_pressure=0.22,
            )
        if name == "split":
            return LatexLayoutSettings(
                name=name,
                is_landscape=True,
                max_visible_columns=self._MAX_VISIBLE_COLUMNS_SPLIT_BLOCK,
                tabcolsep_pt=self._MIN_TABCOLSEP_PT,
                font_command="\\footnotesize",
                target_width_fraction=0.98,
                max_pressure=0.24,
            )
        raise ValueError(f"Unknown LaTeX layout mode: {name}")

    @staticmethod
    def _geometry_options(layout: LatexLayoutSettings) -> str:
        if layout.is_landscape:
            margin = "0.48in" if layout.name in {"landscape-compact", "split"} else "0.5in"
            return f"landscape, margin={margin}"
        return "margin=0.65in"

    @staticmethod
    def _arraystretch_for_layout(style: TableStyle, layout: LatexLayoutSettings) -> float:
        if layout.name in {"landscape-compact", "split"}:
            return round(max(1.0, min(style.line_height, 1.24)), 2)
        return round(max(1.0, min(style.line_height, 1.42)), 2)

    def _columns_fit_layout(
        self,
        table: GeneratedTable,
        columns: list[ColumnSchema],
        layout: LatexLayoutSettings,
    ) -> bool:
        """Return whether a candidate set of data columns can stay in one LaTeX block."""

        if not self._within_visible_column_limit(columns, layout):
            return False

        dtypes = ["anchor", *[column.dtype for column in columns]]
        minimum_width = sum(self._layout_minimum_width(dtype, layout) for dtype in dtypes)
        if minimum_width > layout.target_width_fraction:
            return False

        ideal_width = self._layout_minimum_width("anchor", layout) + sum(
            self._layout_ideal_width(table, column, layout) for column in columns
        )
        if ideal_width <= layout.target_width_fraction:
            return True

        compression_room = ideal_width - minimum_width
        if compression_room <= 0:
            return True

        compression_ratio = (layout.target_width_fraction - minimum_width) / compression_room
        return compression_ratio >= layout.max_pressure

    def _partition_columns_for_layout(
        self,
        table: GeneratedTable,
        layout: LatexLayoutSettings,
    ) -> list[list[ColumnSchema]]:
        """Split data columns into readable contiguous groups that repeat the Record anchor."""

        groups: list[list[ColumnSchema]] = []
        current_group: list[ColumnSchema] = []
        for column in table.schema.columns:
            candidate_group = [*current_group, column]
            if current_group and not self._columns_fit_layout(table, candidate_group, layout):
                groups.append(current_group)
                current_group = [column]
            else:
                current_group = candidate_group

        if current_group:
            groups.append(current_group)
        return groups or [list(table.schema.columns)]

    @staticmethod
    def _visible_column_count(columns: list[ColumnSchema]) -> int:
        """Count user-visible LaTeX columns, including the repeated Record anchor."""

        return 1 + len(columns)

    def _within_visible_column_limit(
        self,
        columns: list[ColumnSchema],
        layout: LatexLayoutSettings,
    ) -> bool:
        """Apply the explicit visual column ceiling before any width heuristics."""

        return self._visible_column_count(columns) <= layout.max_visible_columns

    def _detail_sections(
        self,
        table: GeneratedTable,
        style: TableStyle,
        column_groups: list[list[ColumnSchema]],
        layout: LatexLayoutSettings,
    ) -> list[dict[str, object]]:
        """Build readable detail tables while repeating the Record anchor."""

        sections: list[dict[str, object]] = []
        for section_index, columns in enumerate(column_groups, start=1):
            section_dtypes = ["anchor", *[column.dtype for column in columns]]
            section_kinds = ["compact", *[self._column_kind(column.dtype) for column in columns]]
            width_fractions = self._section_width_fractions(table, columns, layout)
            font_command = self._section_font_command(len(section_dtypes), len(column_groups), layout)
            section_columns = [LatexColumnView(header_escaped="Record")] + [
                LatexColumnView(header_escaped=self._escape_latex(self._display_name(column.name)))
                for column in columns
            ]
            section_rows = [
                [
                    self._escape_latex(f"Record {row_index:03d}"),
                    *[
                        self._format_latex_cell_value(
                            raw_value=row.get(column.name),
                            column=column,
                            width_fraction=width_fractions[column_index + 1],
                            is_landscape=layout.is_landscape,
                            font_command=font_command,
                            tabcolsep_pt=layout.tabcolsep_pt,
                        )
                        for column_index, column in enumerate(columns)
                    ],
                ]
                for row_index, row in enumerate(table.rows, start=1)
            ]
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
                        width_fractions=width_fractions,
                    ),
                    "font_command": font_command,
                    "layout_strategy": layout.name,
                }
            )
        return sections

    @staticmethod
    def _section_font_command(
        visible_column_count: int,
        group_count: int,
        layout: LatexLayoutSettings,
    ) -> str:
        if group_count == 1:
            return layout.font_command
        if visible_column_count >= 6:
            return "\\footnotesize"
        return "\\small"

    def _section_width_fractions(
        self,
        table: GeneratedTable,
        columns: list[ColumnSchema],
        layout: LatexLayoutSettings,
    ) -> list[float]:
        """Allocate safe p-column widths for one LaTeX table section."""

        dtypes = ["anchor", *[column.dtype for column in columns]]
        minimums = [self._layout_minimum_width(dtype, layout) for dtype in dtypes]
        ideals = [self._layout_ideal_width_for_dtype("anchor", layout)] + [
            self._layout_ideal_width(table, column, layout) for column in columns
        ]
        flex_weights = [0.7, *[self._layout_flex_weight(table, column) for column in columns]]
        return self._expand_widths_between_minimum_and_ideal(
            minimums=minimums,
            ideals=ideals,
            flex_weights=flex_weights,
            target_total=layout.target_width_fraction,
        )

    def _format_latex_cell_value(
        self,
        raw_value: object,
        column: ColumnSchema,
        width_fraction: float,
        is_landscape: bool,
        font_command: str,
        tabcolsep_pt: float,
    ) -> str:
        """Format one cell, capping long textual content to about three visual lines."""

        if raw_value is None:
            return ""

        if not self._should_limit_long_text_cell(column):
            return self._escape_latex(str(raw_value))

        chars_per_visual_line = self._long_text_chars_per_visual_line(
            width_fraction=width_fraction,
            is_landscape=is_landscape,
            font_command=font_command,
            tabcolsep_pt=tabcolsep_pt,
        )
        return self._format_long_text_for_latex_cell(
            raw_text=str(raw_value),
            chars_per_visual_line=chars_per_visual_line,
        )

    @staticmethod
    def _should_limit_long_text_cell(column: ColumnSchema) -> bool:
        """Limit only intentionally long text columns, leaving compact fields untouched."""

        return column.dtype == "text_long"

    def _format_long_text_for_latex_cell(
        self,
        raw_text: str,
        chars_per_visual_line: int | None = None,
    ) -> str:
        """Wrap long text into at most three word-safe LaTeX cell lines."""

        collapsed = " ".join(raw_text.split())
        if not collapsed:
            return ""
        if len(collapsed) <= self._LONG_TEXT_WRAP_THRESHOLD:
            return self._escape_latex(collapsed)

        estimated_target = max(
            self._LONG_TEXT_MIN_CHARS_PER_LINE,
            math.ceil(len(collapsed) / self._LONG_TEXT_MAX_VISUAL_LINES),
        )
        if chars_per_visual_line is not None:
            estimated_target = min(estimated_target, max(self._LONG_TEXT_MIN_CHARS_PER_LINE, chars_per_visual_line))

        lines, did_truncate = self._split_long_text_cell_lines(collapsed, estimated_target)
        escaped_lines = [self._escape_latex(line) for line in lines if line]
        if not escaped_lines:
            return ""
        if did_truncate:
            escaped_lines[-1] = f"{escaped_lines[-1]}{self._LONG_TEXT_TRUNCATION_SUFFIX}"
        return r"\newline ".join(escaped_lines)

    def _split_long_text_cell_lines(self, text: str, line_target: int) -> tuple[list[str], bool]:
        """Split text into up to three lines, choosing breaks near word boundaries."""

        lines: list[str] = []
        remaining = text.strip()
        for line_index in range(self._LONG_TEXT_MAX_VISUAL_LINES):
            slots_left = self._LONG_TEXT_MAX_VISUAL_LINES - line_index
            if not remaining:
                break
            if len(remaining) <= line_target or slots_left == 1:
                line, did_truncate = self._truncate_cell_line_by_words(remaining, line_target)
                lines.append(line)
                return lines, did_truncate

            dynamic_target = max(
                self._LONG_TEXT_MIN_CHARS_PER_LINE,
                min(line_target, math.ceil(len(remaining) / slots_left)),
            )
            break_index = self._nearest_word_boundary(remaining, dynamic_target)
            if break_index >= len(remaining):
                lines.append(remaining)
                return lines, False

            line = remaining[:break_index].strip()
            if not line:
                line, did_truncate = self._truncate_cell_line_by_words(remaining, line_target)
                lines.append(line)
                return lines, did_truncate

            lines.append(line)
            remaining = remaining[break_index:].strip()

        return lines, bool(remaining)

    def _long_text_chars_per_visual_line(
        self,
        width_fraction: float,
        is_landscape: bool,
        font_command: str,
        tabcolsep_pt: float,
    ) -> int:
        """Estimate how much text fits in three wrapped LaTeX cell lines."""

        full_line_chars = 146 if is_landscape else 92
        font_multiplier = {
            "\\small": 1.0,
            "\\footnotesize": 1.12,
            "\\scriptsize": 1.28,
        }.get(font_command, 1.0)
        padding_penalty = max(2, int(round(tabcolsep_pt * 1.2)))
        chars_per_line = int(full_line_chars * font_multiplier * max(width_fraction, 0.05)) - padding_penalty
        return max(self._LONG_TEXT_MIN_CHARS_PER_LINE, chars_per_line)

    @staticmethod
    def _nearest_word_boundary(text: str, target_index: int) -> int:
        """Return a nearby whitespace boundary, preferring the next word end when balanced."""

        if len(text) <= target_index:
            return len(text)

        target_index = max(1, min(target_index, len(text) - 1))
        if text[target_index].isspace():
            return target_index

        after_index = -1
        for index in range(target_index + 1, len(text)):
            if text[index].isspace():
                after_index = index
                break

        before_index = -1
        for index in range(target_index - 1, 0, -1):
            if text[index].isspace():
                before_index = index
                break

        if after_index == -1 and before_index == -1:
            return len(text)
        if after_index == -1:
            return before_index
        if before_index == -1:
            return after_index

        after_distance = after_index - target_index
        before_distance = target_index - before_index
        if after_distance <= before_distance * 1.35 + 2:
            return after_index
        return before_index

    @staticmethod
    def _truncate_cell_line_by_words(value: str, char_limit: int) -> tuple[str, bool]:
        """Truncate a line on a word boundary without cutting through a word."""

        if len(value) <= char_limit:
            return value, False

        cutoff = max(1, char_limit)
        candidate = value[:cutoff].rstrip()
        word_boundary = candidate.rfind(" ")
        if word_boundary > 0:
            return candidate[:word_boundary].rstrip(" ,;:."), True

        next_boundary = value.find(" ", cutoff)
        if next_boundary > 0:
            return value[:next_boundary].rstrip(" ,;:."), True
        return value, False

    def _column_layout_score(self, table: GeneratedTable, column: ColumnSchema) -> float:
        """Estimate visual width pressure from dtype, header length, and sampled content."""

        display_name = self._display_name(column.name)
        raw_values = [row.get(column.name) for row in table.rows[:30]]
        values = ["" if value is None else str(value).strip() for value in raw_values]
        non_empty_values = [value for value in values if value]
        lengths = [len(display_name), *[min(len(value), 80) for value in non_empty_values]]
        average_length = sum(lengths) / len(lengths) if lengths else len(display_name)
        max_length = max(lengths) if lengths else len(display_name)
        wordy_values = sum(" " in value for value in non_empty_values)

        kind = self._column_kind(column.dtype)
        base = {
            "compact": 0.68,
            "text": 1.05,
            "long_text": 2.05,
        }.get(kind, 1.0)
        score = base + min(len(display_name), 28) * 0.028 + min(average_length, 48) * 0.018 + min(max_length, 80) * 0.006
        if kind == "long_text":
            score += min(wordy_values, 12) * 0.035
        if column.dtype in self._NUMERIC_DTYPES:
            score *= 0.78
        if column.dtype in {"date", "identifier", "alphanumeric_code", "symbolic_mixed"}:
            score *= 0.86
        return score

    def _layout_ideal_width(
        self,
        table: GeneratedTable,
        column: ColumnSchema,
        layout: LatexLayoutSettings,
    ) -> float:
        """Return the preferred width for one column before compression is considered."""

        base = self._layout_ideal_width_for_dtype(column.dtype, layout)
        content_bonus = min(self._column_layout_score(table, column), 3.0) * 0.008
        if column.dtype == "text_long":
            return min(base + content_bonus, 0.235 if layout.is_landscape else 0.255)
        if self._column_kind(column.dtype) == "text":
            return min(base + content_bonus * 0.55, 0.150 if layout.is_landscape else 0.170)
        return min(base + content_bonus * 0.25, 0.095 if layout.is_landscape else 0.115)

    def _layout_flex_weight(self, table: GeneratedTable, column: ColumnSchema) -> float:
        """Estimate how much a column benefits from receiving leftover width."""

        kind = self._column_kind(column.dtype)
        base = {
            "long_text": 3.2,
            "text": 1.7,
            "compact": 0.7,
        }.get(kind, 1.0)
        return base + min(self._column_layout_score(table, column), 3.0) * 0.18

    def _layout_minimum_width(self, dtype: str, layout: LatexLayoutSettings) -> float:
        """Return a readability floor for one column under the selected page mode."""

        landscape = layout.is_landscape
        if dtype == "anchor":
            return 0.080 if landscape else 0.105
        if dtype in self._NUMERIC_DTYPES:
            return 0.046 if landscape else 0.064
        if dtype in {"date", "identifier", "alphanumeric_code", "symbolic_mixed"}:
            return 0.056 if landscape else 0.076
        if dtype == "text_long":
            return 0.115 if landscape else 0.150
        return 0.070 if landscape else 0.095

    def _layout_ideal_width_for_dtype(self, dtype: str, layout: LatexLayoutSettings) -> float:
        """Return the preferred readable width for a column type."""

        landscape = layout.is_landscape
        if dtype == "anchor":
            return 0.100 if landscape else 0.125
        if dtype in self._NUMERIC_DTYPES:
            return 0.060 if landscape else 0.080
        if dtype in {"date", "identifier", "alphanumeric_code", "symbolic_mixed"}:
            return 0.074 if landscape else 0.095
        if dtype == "text_long":
            return 0.185 if landscape else 0.215
        return 0.105 if landscape else 0.130

    @staticmethod
    def _expand_widths_between_minimum_and_ideal(
        minimums: list[float],
        ideals: list[float],
        flex_weights: list[float],
        target_total: float,
    ) -> list[float]:
        """Use all available width, expanding from minimums toward ideals and then flexibly beyond."""

        if not minimums:
            return []

        minimum_total = sum(minimums)
        if minimum_total > target_total:
            scaled = [(minimum / minimum_total) * target_total for minimum in minimums]
            scaled[-1] += target_total - sum(scaled)
            return scaled

        widths = list(minimums)
        remaining = target_total - minimum_total
        ideal_gaps = [max(0.0, ideal - minimum) for minimum, ideal in zip(minimums, ideals)]
        gap_total = sum(ideal_gaps)
        if gap_total > 0:
            used = min(remaining, gap_total)
            for index, gap in enumerate(ideal_gaps):
                widths[index] += used * (gap / gap_total)
            remaining -= used

        if remaining > 0:
            total_flex = sum(max(weight, 0.01) for weight in flex_weights) or float(len(widths))
            for index, weight in enumerate(flex_weights):
                widths[index] += remaining * (max(weight, 0.01) / total_flex)

        total_width = sum(widths) or 1.0
        if total_width > target_total:
            widths = [width * (target_total / total_width) for width in widths]
        else:
            widths[-1] += target_total - total_width
        widths[-1] += target_total - sum(widths)
        return widths

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
                points: list[LatexChartPointView] = []
                for index, point in enumerate(chart_chunk):
                    record_label = f"{int(point['row_index']):03d}"
                    points.append(
                        LatexChartPointView(
                            index=self._chart_point_index(
                                raw_index_label=record_label,
                                fallback_row_index=int(point["row_index"]),
                            ),
                            index_label_escaped=self._escape_latex(record_label),
                            plot_position=float(index) * self._CHART_POINT_SPACING,
                            label_escaped=self._escape_latex(record_label),
                            value=float(point["numeric_value"]),
                            value_label_escaped=self._escape_latex(
                                self._format_numeric(float(point["numeric_value"]))
                            ),
                        )
                    )
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
                        "x_max": max(point.plot_position for point in points) + self._CHART_POINT_SPACING,
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
        width_fractions: list[float] | None = None,
    ) -> str:
        """Build the column specification for one LaTeX table."""

        separator = " " if border_style == "minimal" else " "
        resolved_width_fractions = width_fractions or self._column_width_fractions(column_kinds)
        tokens = [
            self._alignment_token(dtype, alignment_profile, resolved_width_fractions[index])
            for index, dtype in enumerate(dtypes)
        ]
        body = separator.join(tokens)
        return f"@{{}}{body}@{{}}"

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
