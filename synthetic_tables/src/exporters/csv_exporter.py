"""CSV exporting utilities for base tables."""

from __future__ import annotations

import csv
from pathlib import Path

from generators.table_generator import GeneratedTable
from utils.io import ensure_parent_dir


class CSVExporter:
    """Export generated base tables to CSV."""

    def export(self, table: GeneratedTable, output_path: Path) -> Path:
        """Write one generated table to CSV."""

        ensure_parent_dir(output_path)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(table.columns)
            for row in table.row_values():
                writer.writerow(["" if value is None else value for value in row])
        return output_path
