"""Generate synthetic base tables from saved schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from generators.column_generators import build_column_generator
from generators.schema_generator import SchemaGenerator, TableSchema


@dataclass
class GeneratedTable:
    """Represent one generated base table."""

    table_id: str
    name: str
    seed: int
    columns: list[str]
    rows: list[dict[str, Any]]
    schema: TableSchema
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def n_rows(self) -> int:
        """Return the number of generated rows."""

        return len(self.rows)

    @property
    def n_cols(self) -> int:
        """Return the number of generated columns."""

        return len(self.columns)

    def row_values(self) -> list[list[Any]]:
        """Return rows ordered by the schema column order."""

        return [[row.get(column) for column in self.columns] for row in self.rows]


class TableGenerator:
    """Create concrete synthetic tables from schemas."""

    def __init__(self, schema_generator: SchemaGenerator | None = None) -> None:
        self.schema_generator = schema_generator or SchemaGenerator()

    def generate(
        self,
        table_name: str,
        seed: int,
        row_count: int | None = None,
        column_count: int | None = None,
    ) -> GeneratedTable:
        """Generate a full table from a newly sampled schema."""

        schema = self.schema_generator.generate(
            table_name=table_name,
            seed=seed,
            row_count=row_count,
            column_count=column_count,
        )
        return self.generate_from_schema(schema)

    def generate_from_schema(self, schema: TableSchema) -> GeneratedTable:
        """Generate row dictionaries for a provided schema."""

        generated_columns: dict[str, list[Any]] = {}
        for column_index, column in enumerate(schema.columns):
            generator = build_column_generator(column=column, seed=schema.seed + column_index)
            generated_columns[column.name] = generator.generate_values(
                column=column,
                row_count=schema.row_count,
            )

        rows: list[dict[str, Any]] = []
        for row_index in range(schema.row_count):
            row = {
                column.name: generated_columns[column.name][row_index]
                for column in schema.columns
            }
            rows.append(row)

        return GeneratedTable(
            table_id=schema.table_id,
            name=schema.name,
            seed=schema.seed,
            columns=[column.name for column in schema.columns],
            rows=rows,
            schema=schema,
            metadata={
                "generator_stage": "stage_2_base_tables",
                "column_types": [column.dtype for column in schema.columns],
            },
        )
