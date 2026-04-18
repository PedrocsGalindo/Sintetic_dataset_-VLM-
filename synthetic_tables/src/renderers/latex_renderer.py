"""LaTeX renderer for generated tables."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from generators.table_generator import GeneratedTable
from styles.style_sampler import TableStyle
from utils.io import write_text_file


@dataclass(frozen=True)
class LatexColumnView:
    """Represent one LaTeX-facing column configuration."""

    header_escaped: str


class LatexRenderer:
    """Render a generated table to a styled LaTeX string."""

    def __init__(self, template_dir: Path | None = None) -> None:
        resolved_template_dir = template_dir or Path(__file__).resolve().parents[1] / "styles" / "templates" / "latex"
        self.environment = Environment(
            loader=FileSystemLoader(str(resolved_template_dir)),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, table: GeneratedTable, style: TableStyle) -> str:
        """Create a LaTeX representation of the table."""

        template = self.environment.get_template(style.template_name)
        column_kinds = [self._column_kind(column.dtype) for column in table.schema.columns]
        columns = [
            LatexColumnView(header_escaped=self._escape_latex(column_schema.name.replace("_", " ").title()))
            for column_schema in table.schema.columns
        ]
        rows = [
            [
                self._escape_latex("" if row[column_name] is None else str(row[column_name]))
                for column_name in table.columns
            ]
            for row in table.rows
        ]
        is_landscape = len(table.columns) >= 7 or sum(kind == "long_text" for kind in column_kinds) >= 3
        latex_options = {
            "column_spec": self._column_spec(table, style, column_kinds),
            "arraystretch": max(1.0, style.line_height),
            "tabcolsep_pt": min(style.padding, 4 if is_landscape else 5),
            "has_horizontal_rules": style.border_style != "minimal",
            "geometry_options": "landscape, margin=0.45in" if is_landscape else "margin=0.7in",
            "is_landscape": is_landscape,
        }
        return template.render(
            table={
                "name_escaped": self._escape_latex(table.name),
                "display_name_escaped": self._escape_latex(table.name.replace("_", " ").title()),
            },
            columns=columns,
            rows=rows,
            style=style,
            latex=latex_options,
        )

    def render_to_file(self, table: GeneratedTable, style: TableStyle, output_path: Path) -> Path:
        """Write a rendered LaTeX file to disk."""

        latex = self.render(table, style)
        write_text_file(output_path, latex)
        return output_path

    def _column_spec(self, table: GeneratedTable, style: TableStyle, column_kinds: list[str]) -> str:
        """Build the column specification for the LaTeX table."""

        if style.border_style == "minimal":
            separator = " "
        else:
            separator = " | "

        width_fractions = self._column_width_fractions(column_kinds)
        tokens = [
            self._alignment_token(column.dtype, style.alignment_profile, width_fractions[index])
            for index, column in enumerate(table.schema.columns)
        ]
        body = separator.join(tokens)
        if style.border_style == "minimal":
            return body
        return f"| {body} |"

    @staticmethod
    def _alignment_token(dtype: str, alignment_profile: str, width_fraction: float) -> str:
        width = f"{width_fraction:.3f}\\linewidth"
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
        """Allocate most of the line width to descriptive columns while keeping compact fields narrow."""

        weight_map = {
            "long_text": 1.9,
            "text": 1.05,
            "compact": 0.75,
        }
        weights = [weight_map.get(kind, 1.0) for kind in column_kinds]
        total_weight = sum(weights) or float(len(column_kinds))
        target_total = 0.95 if len(column_kinds) >= 10 else 0.97 if len(column_kinds) >= 7 else 0.99
        return [(weight / total_weight) * target_total for weight in weights]

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
