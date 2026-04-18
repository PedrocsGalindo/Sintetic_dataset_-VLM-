"""Project configuration for the synthetic tables pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from utils.io import ensure_project_layout


@dataclass(frozen=True)
class ProjectPaths:
    """Centralize filesystem paths used across the project."""

    project_root: Path
    data_dir: Path = field(init=False)
    base_tables_dir: Path = field(init=False)
    rendered_dir: Path = field(init=False)
    metadata_dir: Path = field(init=False)
    src_dir: Path = field(init=False)
    base_csv_dir: Path = field(init=False)
    base_xlsx_dir: Path = field(init=False)
    schemas_dir: Path = field(init=False)
    rendered_html_dir: Path = field(init=False)
    rendered_latex_dir: Path = field(init=False)
    rendered_markdown_dir: Path = field(init=False)
    rendered_pdf_dir: Path = field(init=False)
    rendered_images_dir: Path = field(init=False)
    tables_metadata_path: Path = field(init=False)
    samples_metadata_path: Path = field(init=False)

    def __post_init__(self) -> None:
        data_dir = self.project_root / "data"
        base_tables_dir = data_dir / "base_tables"
        rendered_dir = data_dir / "rendered"
        metadata_dir = data_dir / "metadata"

        object.__setattr__(self, "data_dir", data_dir)
        object.__setattr__(self, "base_tables_dir", base_tables_dir)
        object.__setattr__(self, "rendered_dir", rendered_dir)
        object.__setattr__(self, "metadata_dir", metadata_dir)
        object.__setattr__(self, "src_dir", self.project_root / "src")
        object.__setattr__(self, "base_csv_dir", base_tables_dir / "csv")
        object.__setattr__(self, "base_xlsx_dir", base_tables_dir / "xlsx")
        object.__setattr__(self, "schemas_dir", base_tables_dir / "schemas")
        object.__setattr__(self, "rendered_html_dir", rendered_dir / "html")
        object.__setattr__(self, "rendered_latex_dir", rendered_dir / "latex")
        object.__setattr__(self, "rendered_markdown_dir", rendered_dir / "markdown")
        object.__setattr__(self, "rendered_pdf_dir", rendered_dir / "pdf")
        object.__setattr__(self, "rendered_images_dir", rendered_dir / "images")
        object.__setattr__(self, "tables_metadata_path", metadata_dir / "tables.jsonl")
        object.__setattr__(self, "samples_metadata_path", metadata_dir / "samples.jsonl")

    def directories(self) -> tuple[Path, ...]:
        """Return the directories that should exist for the pipeline."""

        return (
            self.project_root,
            self.data_dir,
            self.base_tables_dir,
            self.rendered_dir,
            self.metadata_dir,
            self.src_dir,
            self.base_csv_dir,
            self.base_xlsx_dir,
            self.schemas_dir,
            self.rendered_html_dir,
            self.rendered_latex_dir,
            self.rendered_markdown_dir,
            self.rendered_pdf_dir,
            self.rendered_images_dir,
        )

    def files(self) -> tuple[Path, ...]:
        """Return the metadata files that should exist for the pipeline."""

        return (
            self.tables_metadata_path,
            self.samples_metadata_path,
        )


@dataclass(frozen=True)
class GenerationSettings:
    """Store tunable generation parameters for the end-to-end pipeline."""

    table_count: int = 4
    visual_versions: int = 2
    seed: int = 42
    min_rows: int = 40
    max_rows: int = 100
    min_cols: int = 5
    max_cols: int = 12
    dpis: tuple[int, ...] = (100, 300)
    source_formats: tuple[str, ...] = ("html", "latex", "markdown")

    def validate(self) -> None:
        """Validate runtime settings before the pipeline starts."""

        if self.table_count <= 0:
            raise ValueError("table_count must be greater than zero.")
        if self.visual_versions <= 0:
            raise ValueError("visual_versions must be greater than zero.")
        if self.min_rows <= 0 or self.max_rows <= 0:
            raise ValueError("Row limits must be positive integers.")
        if self.min_cols <= 0 or self.max_cols <= 0:
            raise ValueError("Column limits must be positive integers.")
        if self.min_rows > self.max_rows:
            raise ValueError("min_rows cannot be greater than max_rows.")
        if self.min_cols > self.max_cols:
            raise ValueError("min_cols cannot be greater than max_cols.")
        if not self.dpis:
            raise ValueError("At least one DPI value must be provided.")
        if any(dpi <= 0 for dpi in self.dpis):
            raise ValueError("All DPI values must be positive integers.")
        if not self.source_formats:
            raise ValueError("At least one source format must be provided.")
        unsupported_formats = set(self.source_formats) - {"html", "latex", "markdown"}
        if unsupported_formats:
            raise ValueError(f"Unsupported source formats: {sorted(unsupported_formats)}")


@dataclass(frozen=True)
class PipelineConfig:
    """Store high-level runtime settings for the pipeline."""

    project_name: str
    current_stage: str
    paths: ProjectPaths
    settings: GenerationSettings

    def prepare_workspace(self) -> None:
        """Create the expected directory tree and placeholder files."""

        self.settings.validate()
        ensure_project_layout(self.paths.directories(), self.paths.files())

    def with_settings(self, **overrides: object) -> "PipelineConfig":
        """Return a copy with updated generation settings."""

        updated_settings = replace(self.settings, **overrides)
        updated_settings.validate()
        return replace(self, settings=updated_settings)


def build_default_config() -> PipelineConfig:
    """Build the default end-to-end pipeline configuration."""

    project_root = Path(__file__).resolve().parents[1]
    paths = ProjectPaths(project_root=project_root)
    return PipelineConfig(
        project_name="synthetic_tables",
        current_stage="stage_5_final",
        paths=paths,
        settings=GenerationSettings(),
    )
