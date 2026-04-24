"""Schema generation for synthetic base tables."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from utils.ids import make_id, slugify
from utils.io import ensure_parent_dir

SUPPORTED_COLUMN_TYPES: tuple[str, ...] = (
    "text_short",
    "text_long",
    "integer",
    "decimal",
    "percentage",
    "fraction",
    "date",
    "identifier",
    "alphanumeric_code",
    "symbolic_mixed",
)

DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",
    "%d/%m/%Y",
)

COLUMN_NAME_CANDIDATES: dict[str, tuple[str, ...]] = {
    "text_short": ("status", "category", "region", "group", "label", "class"),
    "text_long": ("description", "notes", "summary", "remarks", "details", "comment"),
    "integer": ("quantity", "units", "count", "rank", "index", "score"),
    "decimal": ("amount", "value", "balance", "metric", "price", "ratio"),
    "percentage": ("coverage", "success_rate", "completion", "utilization", "share", "ratio_pct"),
    "fraction": ("mix", "split", "allocation", "composition", "part_ratio", "portion"),
    "date": ("event_date", "issue_date", "recorded_on", "created_at", "updated_at", "due_date"),
    "identifier": ("record_id", "invoice_id", "batch_id", "entry_id", "ticket_id", "entity_id"),
    "alphanumeric_code": ("product_code", "serial_code", "tag_code", "asset_code", "unit_code", "ref_code"),
    "symbolic_mixed": ("marker", "signature", "token", "flag_code", "signal", "pattern"),
}


@dataclass
class ColumnSchema:
    """Describe one generated column."""

    name: str
    dtype: str
    nullable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert the column schema to a serializable mapping."""

        return {
            "name": self.name,
            "dtype": self.dtype,
            "nullable": self.nullable,
            "metadata": self.metadata,
        }


@dataclass
class TableSchema:
    """Describe the structure of one synthetic base table."""

    table_id: str
    name: str
    columns: list[ColumnSchema]
    row_count: int
    seed: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def column_count(self) -> int:
        """Return the number of columns in the table."""

        return len(self.columns)

    def to_dict(self) -> dict[str, Any]:
        """Convert the table schema to a serializable mapping."""

        return {
            "table_id": self.table_id,
            "name": self.name,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "seed": self.seed,
            "columns": [column.to_dict() for column in self.columns],
            "metadata": self.metadata,
        }


class SchemaGenerator:
    """Build synthetic schemas for stage-2 base table generation."""

    def __init__(
        self,
        min_columns: int = 5,
        max_columns: int = 12,
        min_rows: int = 40,
        max_rows: int = 100,
        allow_nullable_cells: bool = False,
    ) -> None:
        self.min_columns = min_columns
        self.max_columns = max_columns
        self.min_rows = min_rows
        self.max_rows = max_rows
        self.allow_nullable_cells = allow_nullable_cells

    def generate(
        self,
        table_name: str,
        seed: int,
        row_count: int | None = None,
        column_count: int | None = None,
        forced_dtypes: Sequence[str] | None = None,
    ) -> TableSchema:
        """Create one schema with column-level type coherence."""

        rng = random.Random(seed)
        resolved_row_count = row_count if row_count is not None else rng.randint(self.min_rows, self.max_rows)
        resolved_column_count = (
            column_count if column_count is not None else rng.randint(self.min_columns, self.max_columns)
        )

        chosen_dtypes = list(forced_dtypes or [])
        while len(chosen_dtypes) < resolved_column_count:
            chosen_dtypes.append(rng.choice(SUPPORTED_COLUMN_TYPES))
        rng.shuffle(chosen_dtypes)

        used_names: set[str] = set()
        columns = [
            self._build_column_schema(dtype=dtype, index=index, rng=rng, used_names=used_names)
            for index, dtype in enumerate(chosen_dtypes[:resolved_column_count], start=1)
        ]

        return TableSchema(
            table_id=make_id("tbl"),
            name=slugify(table_name),
            columns=columns,
            row_count=resolved_row_count,
            seed=seed,
            metadata={
                "generator_stage": "stage_2_base_tables",
                "column_types": [column.dtype for column in columns],
            },
        )

    def generate_batch(self, table_count: int, seed: int) -> list[TableSchema]:
        """Create a batch of schemas while spreading the supported dtypes."""

        rng = random.Random(seed)
        coverage_pool = list(SUPPORTED_COLUMN_TYPES)
        rng.shuffle(coverage_pool)
        schemas: list[TableSchema] = []

        for table_index in range(table_count):
            row_count = rng.randint(self.min_rows, self.max_rows)
            column_count = rng.randint(self.min_columns, self.max_columns)
            table_seed = rng.randint(0, 10**9)
            forced_dtypes: list[str] = []

            while coverage_pool and len(forced_dtypes) < min(2, column_count):
                forced_dtypes.append(coverage_pool.pop())

            schema = self.generate(
                table_name=f"base_table_{table_index + 1:03d}",
                seed=table_seed,
                row_count=row_count,
                column_count=column_count,
                forced_dtypes=forced_dtypes,
            )
            schemas.append(schema)

        return schemas

    def save_schema(self, schema: TableSchema, output_path: Path) -> Path:
        """Persist one schema to disk as JSON."""

        ensure_parent_dir(output_path)
        output_path.write_text(
            json.dumps(schema.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return output_path

    def from_schema_file(self, schema_path: Path) -> TableSchema:
        """Load a schema definition from a saved JSON file."""

        payload = json.loads(schema_path.read_text(encoding="utf-8"))
        columns = [ColumnSchema(**column_payload) for column_payload in payload["columns"]]
        return TableSchema(
            table_id=payload["table_id"],
            name=payload["name"],
            columns=columns,
            row_count=payload["row_count"],
            seed=payload["seed"],
            metadata=payload.get("metadata", {}),
        )

    def _build_column_schema(
        self,
        dtype: str,
        index: int,
        rng: random.Random,
        used_names: set[str],
    ) -> ColumnSchema:
        """Build a column schema tailored to the requested dtype."""

        base_name = rng.choice(COLUMN_NAME_CANDIDATES[dtype])
        name = self._make_unique_name(base_name, index, used_names)
        nullable = self.allow_nullable_cells and rng.random() < 0.85
        null_probability = round(rng.uniform(0.03, 0.12), 3) if nullable else 0.0
        metadata: dict[str, Any] = {"null_probability": null_probability}

        if dtype == "text_short":
            metadata.update({"min_words": 1, "max_words": 3, "title_case": rng.random() < 0.5})
        elif dtype == "text_long":
            metadata.update({"min_words": 6, "max_words": 14})
        elif dtype == "integer":
            start = rng.randint(0, 500)
            metadata.update({"min_value": start, "max_value": start + rng.randint(150, 4000)})
        elif dtype == "decimal":
            lower_bound = round(rng.uniform(0.5, 100.0), 2)
            metadata.update(
                {
                    "min_value": lower_bound,
                    "max_value": round(lower_bound + rng.uniform(25.0, 2000.0), 2),
                    "precision": rng.choice((2, 3)),
                }
            )
        elif dtype == "percentage":
            metadata.update({"precision": rng.choice((0, 1, 2)), "scale": 100})
        elif dtype == "fraction":
            max_denominator = rng.randint(10, 40)
            metadata.update(
                {
                    "max_numerator": rng.randint(3, max_denominator - 1),
                    "max_denominator": max_denominator,
                }
            )
        elif dtype == "date":
            metadata.update({"date_format": rng.choice(DATE_FORMATS), "year": rng.choice((2022, 2023, 2024, 2025))})
        elif dtype == "identifier":
            metadata.update({"prefix": rng.choice(("INV", "REC", "DOC", "LOT", "REF", "ORD")), "start": rng.randint(1000, 9000)})
        elif dtype == "alphanumeric_code":
            metadata.update(
                {
                    "segments": rng.choice(((3, 3), (2, 4), (4, 2))),
                    "separator": rng.choice(("-", "_", "/")),
                }
            )
        elif dtype == "symbolic_mixed":
            metadata.update({"symbols": rng.choice(("@#", "$%", "!*", "&+"))})

        return ColumnSchema(
            name=name,
            dtype=dtype,
            nullable=nullable,
            metadata=metadata,
        )

    @staticmethod
    def _make_unique_name(base_name: str, index: int, used_names: set[str]) -> str:
        """Create a unique column name inside one schema."""

        candidate = slugify(base_name)
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate

        suffixed_candidate = f"{candidate}_{index}"
        used_names.add(suffixed_candidate)
        return suffixed_candidate
