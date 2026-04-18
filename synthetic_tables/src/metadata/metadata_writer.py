"""Metadata writers for base tables and rendered samples."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from generators.table_generator import GeneratedTable
from utils.io import append_jsonl, ensure_parent_dir


class MetadataWriter:
    """Persist metadata as JSONL files."""

    def __init__(self, tables_metadata_path: Path, samples_metadata_path: Path) -> None:
        self.tables_metadata_path = tables_metadata_path
        self.samples_metadata_path = samples_metadata_path

    def reset_tables_metadata(self) -> Path:
        """Start a fresh tables metadata file for a new generation run."""

        ensure_parent_dir(self.tables_metadata_path)
        self.tables_metadata_path.write_text("", encoding="utf-8")
        return self.tables_metadata_path

    def reset_samples_metadata(self) -> Path:
        """Start a fresh samples metadata file for a new generation run."""

        ensure_parent_dir(self.samples_metadata_path)
        self.samples_metadata_path.write_text("", encoding="utf-8")
        return self.samples_metadata_path

    def write_table_metadata(
        self,
        table: GeneratedTable,
        csv_path: Path,
        xlsx_path: Path,
        schema_path: Path,
    ) -> dict[str, Any]:
        """Append one base-table metadata record."""

        self._require_existing_path(csv_path)
        self._require_existing_path(xlsx_path)
        self._require_existing_path(schema_path)

        record = {
            "table_id": table.table_id,
            "seed": table.seed,
            "name": table.name,
            "n_rows": table.n_rows,
            "n_cols": table.n_cols,
            "columns": [column.to_dict() for column in table.schema.columns],
            "csv_path": str(csv_path),
            "xlsx_path": str(xlsx_path),
            "schema_path": str(schema_path),
        }
        append_jsonl(self.tables_metadata_path, record)
        return record

    def write_sample_metadata(
        self,
        sample_id: str,
        table_id: str,
        visual_version: str,
        source_format: str,
        renderer: str,
        style_id: str,
        font_family: str,
        font_size_pt: int,
        dpi: int,
        pages: int,
        page_image_paths: list[Path],
        pdf_path: Path,
        csv_path: Path,
        xlsx_path: Path,
        n_rows: int,
        n_cols: int,
    ) -> dict[str, Any]:
        """Append one rendered sample metadata record to disk."""

        self._require_existing_path(pdf_path)
        self._require_existing_path(csv_path)
        self._require_existing_path(xlsx_path)
        if pages != len(page_image_paths):
            raise ValueError("pages must match the number of page_image_paths.")
        for image_path in page_image_paths:
            self._require_existing_path(image_path)

        record = {
            "sample_id": sample_id,
            "table_id": table_id,
            "visual_version": visual_version,
            "source_format": source_format,
            "renderer": renderer,
            "style_id": style_id,
            "font_family": font_family,
            "font_size_pt": font_size_pt,
            "dpi": dpi,
            "pages": pages,
            "page_image_paths": [str(path) for path in page_image_paths],
            "pdf_path": str(pdf_path),
            "csv_path": str(csv_path),
            "xlsx_path": str(xlsx_path),
            "n_rows": n_rows,
            "n_cols": n_cols,
        }
        append_jsonl(self.samples_metadata_path, record)
        return record

    @staticmethod
    def _require_existing_path(path: Path) -> None:
        """Ensure a required artifact exists on disk."""

        if not path.exists():
            raise FileNotFoundError(f"Required artifact not found: {path}")
