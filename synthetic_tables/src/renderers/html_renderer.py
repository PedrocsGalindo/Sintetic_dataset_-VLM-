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
    kind: str


@dataclass(frozen=True)
class HTMLFieldView:
    """Represent one rendered field in a document-style layout."""

    label: str
    value: str
    alignment: str
    kind: str


@dataclass(frozen=True)
class HTMLRecordView:
    """Represent one row repackaged for alternate HTML layouts."""

    record_label: str
    headline: str
    fields: list[HTMLFieldView]
    line_fields: list[HTMLFieldView]
    column_fields: list[HTMLFieldView]
    compact_fields: list[HTMLFieldView]
    text_fields: list[HTMLFieldView]
    narrative: str
    note: str


class HTMLRenderer:
    """Render a generated table to HTML using templates and CSS."""

    _RECORD_HEADER = "Record"
    _FIRST_TEMPLATE_NAME = "simple_tabular.html.j2"
    _FIRST_TEMPLATE_MAX_VISIBLE_COLUMNS = 5

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
        data_columns = self._build_columns(table, style, resolved_width_mode)
        data_rows = [
            ["" if row[column_name] is None else str(row[column_name]) for column_name in table.columns]
            for row in table.rows
        ]
        columns, rows = self._with_record_column(data_columns, data_rows)
        table_sections = self._table_sections_for_template(style.template_name, columns, rows)
        css = {
            "border_style": self._map_border_style(style.border_style),
            "table_layout": "auto" if resolved_width_mode == "auto" else "fixed",
            "header_emphasis_css": self._header_emphasis_css(style.header_emphasis),
            "sheet_width": self._sheet_width(style.template_name, len(table.columns)),
            "table_font_scale": self._table_font_scale(len(table.columns)),
            "record_columns": self._record_column_count(table),
            "dense_grid_columns": self._dense_grid_columns(table),
        }
        if style.template_name == self._FIRST_TEMPLATE_NAME:
            document = self._build_simple_document_view(table, data_columns)
        else:
            document = self._build_document_view(table, columns, rows)
        return template.render(
            table=table,
            style=style,
            columns=columns,
            rows=rows,
            table_sections=table_sections,
            css=css,
            document=document,
        )

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
        widths = self._column_widths(table, width_mode)
        return [
            HTMLColumnView(
                display_name=self._display_name(column_schema.name),
                alignment=self._alignment_for(column_schema.dtype, style.alignment_profile),
                width=widths[column_index],
                kind=self._kind_for_dtype(column_schema.dtype),
            )
            for column_index, column_schema in enumerate(table.schema.columns)
        ]

    def _build_document_view(
        self,
        table: GeneratedTable,
        columns: list[HTMLColumnView],
        rows: list[list[str]],
    ) -> dict[str, object]:
        """Create alternate narrative and block-oriented views from one base table."""

        records: list[HTMLRecordView] = []
        compact_column_count = sum(column.kind in {"compact", "numeric"} for column in columns)
        long_text_column_count = sum(column.kind == "long_text" for column in columns)

        for row_index, row in enumerate(rows, start=1):
            fields: list[HTMLFieldView] = []
            line_fields: list[HTMLFieldView] = []
            column_fields: list[HTMLFieldView] = []
            compact_fields: list[HTMLFieldView] = []
            text_fields: list[HTMLFieldView] = []

            for column_index, (column, cell) in enumerate(zip(columns, row)):
                display_value = cell or "-"
                field = HTMLFieldView(
                    label=column.display_name,
                    value=display_value,
                    alignment=column.alignment,
                    kind=column.kind,
                )

                if column_index < 6:
                    line_fields.append(field)
                elif cell:
                    column_fields.append(field)

                if not cell:
                    continue

                fields.append(field)
                if column.kind in {"compact", "numeric"}:
                    compact_fields.append(field)
                else:
                    text_fields.append(field)

            if text_fields:
                headline = text_fields[0].value
            elif compact_fields:
                headline = " | ".join(f"{field.label}: {field.value}" for field in compact_fields[:2])
            else:
                headline = self._row_label(row_index)

            narrative_fields = fields[: min(len(fields), 6)]
            narrative = " | ".join(f"{field.label}: {field.value}" for field in narrative_fields)
            note = " ".join(field.value for field in text_fields[:2]).strip()
            records.append(
                HTMLRecordView(
                    record_label=self._row_label(row_index),
                    headline=headline,
                    fields=fields,
                    line_fields=line_fields,
                    column_fields=column_fields,
                    compact_fields=compact_fields,
                    text_fields=text_fields,
                    narrative=narrative,
                    note=note,
                )
            )

        stats = [
            {"label": "Rows", "value": str(table.n_rows)},
            {"label": "Columns", "value": str(table.n_cols)},
            {"label": "Long Text Fields", "value": str(long_text_column_count)},
            {"label": "Compact Fields", "value": str(compact_column_count)},
        ]

        metric_groups = [
            {
                "title": record.record_label,
                "entries": record.compact_fields[:6] or record.fields[:4],
                "summary": record.note or record.narrative,
            }
            for record in records
        ]

        stream_rows = [
            {
                "label": record.record_label,
                "segments": record.fields[:7],
            }
            for record in records
        ]

        article_sections = [
            {
                "label": record.record_label,
                "title": record.headline,
                "paragraph": self._paragraph_for_record(record),
                "meta_line": self._meta_line_for_record(record),
                "compact_fields": record.compact_fields[:4],
            }
            for record in records
        ]

        return {
            "title": self._display_name(table.name),
            "slug": table.name,
            "subtitle": (
                "Synthetic document layouts for OCR and VLM extraction tests. "
                "The same structured content is restaged in alternate HTML compositions."
            ),
            "records": records,
            "metric_groups": metric_groups,
            "stream_rows": stream_rows,
            "article_sections": article_sections,
            "article_columns": self._chunk_items(article_sections[: max(6, self._record_column_count(table) * 3)], 2),
            "procedure": self._build_procedure_view(table, columns, records, article_sections),
            "stats": stats,
            "flow_columns": self._record_column_count(table),
        }

    def _build_simple_document_view(
        self,
        table: GeneratedTable,
        columns: list[HTMLColumnView],
    ) -> dict[str, object]:
        """Build the minimal document metadata needed for the simple tabular layout."""

        compact_column_count = sum(column.kind in {"compact", "numeric"} for column in columns)
        long_text_column_count = sum(column.kind == "long_text" for column in columns)
        return {
            "title": self._display_name(table.name),
            "slug": table.name,
            "subtitle": "Simple tabular view of the generated dataset.",
            "stats": [
                {"label": "Rows", "value": str(table.n_rows)},
                {"label": "Columns", "value": str(table.n_cols)},
                {"label": "Long Text Fields", "value": str(long_text_column_count)},
                {"label": "Compact Fields", "value": str(compact_column_count)},
            ],
        }

    @staticmethod
    def _display_name(value: str) -> str:
        """Convert internal slugs into reader-friendly labels."""

        return value.replace("_", " ").title()

    @staticmethod
    def _row_label(row_index: int) -> str:
        """Return the renderer-owned Record value for one table row."""

        return f"Record {row_index:03d}"

    def _with_record_column(
        self,
        data_columns: list[HTMLColumnView],
        data_rows: list[list[str]],
    ) -> tuple[list[HTMLColumnView], list[list[str]]]:
        """Add the synthetic Record column as a regular visible HTML column."""

        columns = [
            HTMLColumnView(
                display_name=self._RECORD_HEADER,
                alignment="left",
                width="auto",
                kind="compact",
            ),
            *data_columns,
        ]
        rows = [
            [self._row_label(row_index), *row]
            for row_index, row in enumerate(data_rows, start=1)
        ]
        return self._with_record_width(columns), rows

    def _with_record_width(self, columns: list[HTMLColumnView]) -> list[HTMLColumnView]:
        """Add Record width while preserving existing data-column proportions when available."""

        if not columns:
            return []
        data_widths = [self._percent_value(column.width) for column in columns[1:]]
        if not data_widths or any(width is None for width in data_widths):
            return self._with_table_widths(columns)

        record_width = 8.5 if len(columns) >= 8 else 11.0
        data_total = sum(width for width in data_widths if width is not None) or 1.0
        data_target = 100.0 - record_width
        resolved_columns = [
            HTMLColumnView(
                display_name=columns[0].display_name,
                alignment=columns[0].alignment,
                width=f"{record_width:.2f}%",
                kind=columns[0].kind,
            )
        ]
        for column, width in zip(columns[1:], data_widths):
            assert width is not None
            resolved_columns.append(
                HTMLColumnView(
                    display_name=column.display_name,
                    alignment=column.alignment,
                    width=f"{(width / data_total) * data_target:.2f}%",
                    kind=column.kind,
                )
            )
        return resolved_columns

    @staticmethod
    def _percent_value(width: str) -> float | None:
        """Parse a percentage width string produced by the HTML planner."""

        stripped = width.strip()
        if not stripped.endswith("%"):
            return None
        try:
            return float(stripped[:-1])
        except ValueError:
            return None

    def _table_sections_for_template(
        self,
        template_name: str,
        columns: list[HTMLColumnView],
        rows: list[list[str]],
    ) -> list[dict[str, object]]:
        """Split the first dense template into Record-anchored horizontal blocks."""

        if not columns:
            return []
        if template_name != self._FIRST_TEMPLATE_NAME or len(columns) <= self._FIRST_TEMPLATE_MAX_VISIBLE_COLUMNS:
            return [{"title": "Full Index", "columns": columns, "rows": rows}]

        record_column = columns[0]
        data_columns = columns[1:]
        data_columns_per_block = max(1, self._FIRST_TEMPLATE_MAX_VISIBLE_COLUMNS - 1)
        sections: list[dict[str, object]] = []
        for section_index, start in enumerate(range(0, len(data_columns), data_columns_per_block), start=1):
            end = start + data_columns_per_block
            section_columns = self._with_table_widths([record_column, *data_columns[start:end]])
            section_rows = [[row[0], *row[1 + start : 1 + end]] for row in rows]
            sections.append(
                {
                    "title": f"Block {section_index}",
                    "columns": section_columns,
                    "rows": section_rows,
                }
            )
        return sections

    def _with_table_widths(self, columns: list[HTMLColumnView]) -> list[HTMLColumnView]:
        """Rebalance widths for the columns that are visible in one HTML table."""

        if not columns:
            return []
        weights = {
            "numeric": 0.75,
            "compact": 0.90,
            "text": 1.25,
            "long_text": 2.10,
        }
        scores = [weights.get(column.kind, 1.0) for column in columns]
        minimums = [self._html_kind_minimum_percent(column.kind, len(columns)) for column in columns]
        widths = self._normalize_percent_widths(scores, minimums)
        return [
            HTMLColumnView(
                display_name=column.display_name,
                alignment=column.alignment,
                width=f"{widths[index]:.2f}%",
                kind=column.kind,
            )
            for index, column in enumerate(columns)
        ]

    @staticmethod
    def _kind_for_dtype(dtype: str) -> str:
        """Collapse schema dtypes into coarse HTML presentation buckets."""

        if dtype == "text_long":
            return "long_text"
        if dtype in {"integer", "decimal", "percentage", "fraction"}:
            return "numeric"
        if dtype in {"date", "identifier", "alphanumeric_code", "symbolic_mixed"}:
            return "compact"
        return "text"

    @staticmethod
    def _column_width(column_width_mode: str, column_count: int) -> str:
        if column_width_mode == "fixed":
            return f"{100 / max(column_count, 1):.2f}%"
        if column_width_mode == "balanced":
            return f"{96 / max(column_count, 1):.2f}%"
        return "auto"

    def _column_widths(self, table: GeneratedTable, column_width_mode: str) -> list[str]:
        """Allocate semantic HTML table widths without imposing LaTeX-style column splits."""

        column_count = len(table.schema.columns)
        if column_count <= 0:
            return []
        if column_width_mode in {"fixed", "balanced"} and column_count < 6:
            width = self._column_width(column_width_mode, column_count)
            return [width] * column_count
        if column_width_mode == "auto" and column_count < 6:
            return ["auto"] * column_count

        scores = [self._html_column_width_score(table, column_schema) for column_schema in table.schema.columns]
        minimums = [self._html_column_minimum_percent(column_schema.dtype, column_count) for column_schema in table.schema.columns]
        widths = self._normalize_percent_widths(scores, minimums)
        return [f"{width:.2f}%" for width in widths]

    def _html_column_width_score(self, table: GeneratedTable, column_schema) -> float:
        """Estimate how much horizontal space one HTML column should receive."""

        kind = self._kind_for_dtype(column_schema.dtype)
        base = {
            "long_text": 2.45,
            "text": 1.30,
            "compact": 0.82,
            "numeric": 0.70,
        }.get(kind, 1.0)
        header = self._display_name(column_schema.name)
        values = [
            "" if row.get(column_schema.name) is None else str(row.get(column_schema.name)).strip()
            for row in table.rows[:24]
        ]
        non_empty = [value for value in values if value]
        average_length = (
            sum(min(len(value), 70) for value in non_empty) / len(non_empty)
            if non_empty
            else len(header)
        )
        return base + min(len(header), 24) * 0.025 + min(average_length, 44) * 0.012

    def _html_column_minimum_percent(self, dtype: str, column_count: int) -> float:
        """Keep compact columns narrow while preserving a floor for readable text."""

        return self._html_kind_minimum_percent(self._kind_for_dtype(dtype), column_count)

    @staticmethod
    def _html_kind_minimum_percent(kind: str, column_count: int) -> float:
        """Keep compact columns narrow while preserving a floor for readable text."""

        if column_count >= 10:
            floors = {
                "numeric": 4.6,
                "compact": 5.2,
                "text": 6.4,
                "long_text": 9.0,
            }
        elif column_count >= 7:
            floors = {
                "numeric": 5.4,
                "compact": 6.0,
                "text": 7.4,
                "long_text": 10.5,
            }
        else:
            floors = {
                "numeric": 7.0,
                "compact": 8.0,
                "text": 10.0,
                "long_text": 14.0,
            }
        return floors.get(kind, 7.0)

    @staticmethod
    def _normalize_percent_widths(scores: list[float], minimums: list[float]) -> list[float]:
        """Return widths that sum to 100 while honoring minimums when possible."""

        if not scores:
            return []
        minimum_total = sum(minimums)
        if minimum_total >= 100.0:
            widths = [(minimum / minimum_total) * 100.0 for minimum in minimums]
            widths[-1] += 100.0 - sum(widths)
            return widths

        score_total = sum(scores) or float(len(scores))
        widths = [minimum for minimum in minimums]
        remaining = 100.0 - minimum_total
        for index, score in enumerate(scores):
            widths[index] += remaining * (score / score_total)
        widths[-1] += 100.0 - sum(widths)
        return widths

    @staticmethod
    def _resolved_column_width_mode(column_width_mode: str, column_count: int) -> str:
        """Avoid forcing equal-width columns on wide tables where readability would collapse."""

        if column_count >= 6:
            return "semantic"
        return column_width_mode

    @staticmethod
    def _table_font_scale(column_count: int) -> str:
        if column_count >= 12:
            return "0.78"
        if column_count >= 10:
            return "0.84"
        if column_count >= 8:
            return "0.90"
        return "1"

    @staticmethod
    def _sheet_width(template_name: str, column_count: int) -> str:
        if template_name == "simple_tabular.html.j2":
            return "min(1500px, 98vw)" if column_count >= 10 else "min(1320px, 96vw)"
        if template_name == "default_table.html.j2":
            return "min(1500px, 98vw)" if column_count >= 10 else "min(1320px, 96vw)"
        if template_name == "document_columns.html.j2":
            return "min(1180px, 92vw)"
        if template_name == "document_stream.html.j2":
            return "min(1420px, 97vw)"
        if template_name == "hybrid_mosaic.html.j2":
            return "min(1380px, 96vw)"
        if template_name == "editorial_blocks.html.j2":
            return "min(1320px, 95vw)"
        if template_name == "procedure_form.html.j2":
            return "min(1080px, 92vw)"
        return "min(1280px, 94vw)"

    @staticmethod
    def _record_column_count(table: GeneratedTable) -> int:
        if table.n_cols <= 4:
            return 2
        if table.n_cols >= 10:
            return 3
        return 2

    @staticmethod
    def _dense_grid_columns(table: GeneratedTable) -> int:
        if table.n_cols >= 10:
            return 4
        if table.n_cols >= 6:
            return 3
        return 2

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

    @staticmethod
    def _paragraph_for_record(record: HTMLRecordView) -> str:
        """Turn a record into a document-style paragraph."""

        text_parts = [field.value for field in record.text_fields[:3]]
        compact_parts = [f"{field.label.lower()} {field.value}" for field in record.compact_fields[:3]]
        parts = text_parts + compact_parts
        if not parts:
            return record.narrative

        paragraph = ". ".join(part.rstrip(".") for part in parts if part).strip()
        if not paragraph:
            return record.narrative
        return paragraph + "."

    @staticmethod
    def _meta_line_for_record(record: HTMLRecordView) -> str:
        """Build a compact metadata line for mixed editorial layouts."""

        metadata = [f"{field.label}: {field.value}" for field in record.compact_fields[:4]]
        return " | ".join(metadata)

    @staticmethod
    def _chunk_items(items: list[dict[str, object]], chunk_count: int) -> list[list[dict[str, object]]]:
        """Split items into balanced visual columns."""

        if chunk_count <= 1 or not items:
            return [items]

        columns: list[list[dict[str, object]]] = [[] for _ in range(chunk_count)]
        for index, item in enumerate(items):
            columns[index % chunk_count].append(item)
        return [column for column in columns if column]

    def _build_procedure_view(
        self,
        table: GeneratedTable,
        columns: list[HTMLColumnView],
        records: list[HTMLRecordView],
        article_sections: list[dict[str, object]],
    ) -> dict[str, object]:
        """Build a form-like process document inspired by SOP layouts."""

        first_record = records[0] if records else None
        metadata_fields = first_record.fields[:6] if first_record else []
        slot_labels = (
            "Titulo do processo",
            "Departamento",
            "Informacoes de contato",
            "ID POP",
            "Data efetiva",
            "Numero de revisao",
        )
        info_pairs = [
            {
                "label": slot_labels[index],
                "value": metadata_fields[index].value if index < len(metadata_fields) else "",
            }
            for index in range(len(slot_labels))
        ]
        info_rows = [
            {"left": info_pairs[0], "right": info_pairs[1]},
            {"left": info_pairs[2], "right": info_pairs[3]},
            {"left": info_pairs[4], "right": info_pairs[5]},
        ]

        overview_titles = (
            "Descricao do processo",
            "Objetivo e Escopo",
            "Definicoes e documentos relacionados",
        )
        overview_sections: list[dict[str, str]] = []
        for index, title in enumerate(overview_titles):
            body = (
                str(article_sections[index]["paragraph"])
                if index < len(article_sections)
                else f"Preencha a secao {title.lower()}."
            )
            overview_sections.append({"title": title, "body": body})

        text_indexes = [index for index, column in enumerate(columns) if column.kind in {"long_text", "text"}]
        owner_index = next(
            (index for index, column in enumerate(columns) if column.kind in {"compact", "numeric"}),
            0,
        )

        steps: list[dict[str, str]] = []
        for row_index, record in enumerate(records):
            steps.append(
                {
                    "eap": f"{row_index // 4 + 1}.{row_index % 4}",
                    "task": self._step_task_text(record, text_indexes),
                    "owner": self._step_owner_text(record, owner_index),
                }
            )

        while len(steps) < 14:
            steps.append({"eap": "", "task": "", "owner": ""})

        return {
            "document_type": "Procedimento operacional padrao",
            "logo_text": "LOGO COMPANY",
            "company_name": "Nome da Empresa",
            "company_address": "Endereco, Cidade, Rua CEP",
            "company_contact": "(999) 999-9999, nome_do_usuario@email.com",
            "info_rows": info_rows,
            "overview_sections": overview_sections,
            "steps": steps,
            "table_name": self._display_name(table.name),
        }

    @staticmethod
    def _step_task_text(record: HTMLRecordView, text_indexes: list[int]) -> str:
        """Choose a readable step description from the record."""

        if record.text_fields:
            return record.text_fields[0].value
        if record.fields:
            return record.fields[0].value
        return "Descricao da tarefa"

    @staticmethod
    def _step_owner_text(record: HTMLRecordView, owner_index: int) -> str:
        """Choose a compact owner-like value for the process table."""

        if owner_index < len(record.line_fields):
            value = record.line_fields[owner_index].value
            if value and value != "-":
                return value
        if record.compact_fields:
            return record.compact_fields[0].value
        return "Membro da equipe"
