"""Style sampling for intermediate table representations."""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_STYLE_FORMATS: tuple[str, ...] = ("html", "latex", "markdown")


@dataclass(frozen=True)
class TableStyle:
    """Describe a sampled visual style for one rendered representation."""

    template_name: str
    font_family: str
    font_size_pt: int
    line_height: float
    border_style: str
    alignment_profile: str
    column_width_mode: str
    zebra_striping: bool
    header_emphasis: str
    padding: int
    text_color: str
    header_background: str
    border_color: str
    background_color: str
    accent_color: str
    table_width: str


class StyleSampler:
    """Sample deterministic but varied styles for each output format."""

    def __init__(self, base_seed: int = 42) -> None:
        self.base_seed = base_seed

    def sample(self, output_format: str, table_id: str | None = None) -> TableStyle:
        """Sample a style for the requested output format."""

        normalized_format = output_format.lower()
        if normalized_format not in SUPPORTED_STYLE_FORMATS:
            raise ValueError(f"Unsupported style format: {output_format}")
        seed_material = f"{self.base_seed}:{normalized_format}:{table_id or 'default'}"
        rng = random.Random(seed_material)

        font_choices = {
            "html": ("Georgia", "Trebuchet MS", "Verdana", "Garamond", "Tahoma"),
            "latex": ("lmodern", "ptm", "phv", "ppl"),
            "markdown": ("monospace", "sans-serif", "serif"),
        }
        palettes = (
            {
                "text_color": "#1F2933",
                "header_background": "#DCEBFA",
                "border_color": "#5C6B7A",
                "background_color": "#FFFFFF",
                "accent_color": "#2C5282",
            },
            {
                "text_color": "#2D1F1A",
                "header_background": "#F5E6CC",
                "border_color": "#8A6D3B",
                "background_color": "#FFFDF8",
                "accent_color": "#9C4221",
            },
            {
                "text_color": "#20313B",
                "header_background": "#D8F3E5",
                "border_color": "#4A6B5A",
                "background_color": "#FCFFFD",
                "accent_color": "#276749",
            },
        )
        palette = rng.choice(palettes)

        template_names = {
            "html": (
                "default_table.html.j2",
                "document_columns.html.j2",
                "document_stream.html.j2",
                "numeric_blocks.html.j2",
                "hybrid_mosaic.html.j2",
                "editorial_blocks.html.j2",
                "procedure_form.html.j2",
            ),
            "latex": (
                "executive_brief.tex.j2",
                "editorial_report.tex.j2",
                "data_memo.tex.j2",
                "record_cards.tex.j2",
            ),
            "markdown": (
                "default_markdown",
                "markdown_records",
                "markdown_mixed",
                "markdown_briefing",
            ),
        }

        return TableStyle(
            template_name=rng.choice(template_names.get(normalized_format, ("default_table.html.j2",))),
            font_family=rng.choice(font_choices.get(normalized_format, ("Helvetica",))),
            font_size_pt=rng.randint(9, 13),
            line_height=round(rng.uniform(1.1, 1.6), 2),
            border_style=rng.choice(("solid", "dashed", "double", "minimal")),
            alignment_profile=rng.choice(("left", "center", "numeric_right", "mixed")),
            column_width_mode=rng.choice(("auto", "balanced", "fixed")),
            zebra_striping=rng.random() < 0.55,
            header_emphasis=rng.choice(("bold", "caps", "italic", "smallcaps")),
            padding=rng.randint(4, 10),
            text_color=palette["text_color"],
            header_background=palette["header_background"],
            border_color=palette["border_color"],
            background_color=palette["background_color"],
            accent_color=palette["accent_color"],
            table_width=rng.choice(("88%", "92%", "100%")),
        )


def build_style_id(source_format: str, style: TableStyle) -> str:
    """Build a stable style identifier."""

    safe_font = style.font_family.lower().replace(" ", "_")
    template_stem = Path(style.template_name).stem.replace(".", "_")
    return (
        f"{source_format}_{template_stem}_{safe_font}_{style.font_size_pt}_{style.border_style}_"
        f"{style.alignment_profile}_{style.header_emphasis}"
    )
