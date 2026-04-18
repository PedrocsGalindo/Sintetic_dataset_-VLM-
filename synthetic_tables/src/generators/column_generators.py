"""Column value generators for synthetic base tables."""

from __future__ import annotations

import random
import string
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from generators.schema_generator import ColumnSchema

SHORT_WORDS: tuple[str, ...] = (
    "north",
    "delta",
    "prime",
    "urban",
    "rapid",
    "clear",
    "global",
    "silver",
    "amber",
    "vector",
    "signal",
    "metro",
)

LONG_WORDS: tuple[str, ...] = (
    "analysis",
    "distribution",
    "baseline",
    "capacity",
    "inspection",
    "workflow",
    "tracking",
    "consolidated",
    "scheduling",
    "reference",
    "operation",
    "planning",
    "allocation",
    "compliance",
    "documented",
    "evaluation",
)


@dataclass
class BaseColumnGenerator:
    """Base class for coherent column-level synthetic generation."""

    dtype: str
    rng: random.Random

    def generate_values(self, column: ColumnSchema, row_count: int) -> list[Any]:
        """Generate values for one column."""

        values: list[Any] = []
        for row_index in range(row_count):
            if self._should_emit_empty(column):
                values.append(None)
                continue
            values.append(self._generate_value(column, row_index))
        return values

    def _should_emit_empty(self, column: ColumnSchema) -> bool:
        """Decide whether the next value should be empty."""

        if not column.nullable:
            return False
        null_probability = float(column.metadata.get("null_probability", 0.05))
        return self.rng.random() < null_probability

    def _generate_value(self, column: ColumnSchema, row_index: int) -> Any:
        """Generate one non-empty value."""

        raise NotImplementedError("Column generators must implement _generate_value().")


class TextShortColumnGenerator(BaseColumnGenerator):
    """Generate compact text values."""

    def __init__(self, rng: random.Random) -> None:
        super().__init__(dtype="text_short", rng=rng)

    def _generate_value(self, column: ColumnSchema, row_index: int) -> str:
        min_words = int(column.metadata.get("min_words", 1))
        max_words = int(column.metadata.get("max_words", 3))
        n_words = self.rng.randint(min_words, max_words)
        words = [self.rng.choice(SHORT_WORDS) for _ in range(n_words)]
        value = " ".join(words)
        if column.metadata.get("title_case", False):
            return value.title()
        return value


class TextLongColumnGenerator(BaseColumnGenerator):
    """Generate longer descriptive text values."""

    def __init__(self, rng: random.Random) -> None:
        super().__init__(dtype="text_long", rng=rng)

    def _generate_value(self, column: ColumnSchema, row_index: int) -> str:
        min_words = int(column.metadata.get("min_words", 6))
        max_words = int(column.metadata.get("max_words", 14))
        n_words = self.rng.randint(min_words, max_words)
        tokens = [self.rng.choice(LONG_WORDS if idx % 2 else SHORT_WORDS) for idx in range(n_words)]
        sentence = " ".join(tokens)
        return sentence[:1].upper() + sentence[1:]


class IntegerColumnGenerator(BaseColumnGenerator):
    """Generate integer values."""

    def __init__(self, rng: random.Random) -> None:
        super().__init__(dtype="integer", rng=rng)

    def _generate_value(self, column: ColumnSchema, row_index: int) -> int:
        lower = int(column.metadata.get("min_value", 0))
        upper = int(column.metadata.get("max_value", 1000))
        return self.rng.randint(lower, upper)


class DecimalColumnGenerator(BaseColumnGenerator):
    """Generate decimal values."""

    def __init__(self, rng: random.Random) -> None:
        super().__init__(dtype="decimal", rng=rng)

    def _generate_value(self, column: ColumnSchema, row_index: int) -> float:
        lower = float(column.metadata.get("min_value", 0.5))
        upper = float(column.metadata.get("max_value", 999.9))
        precision = int(column.metadata.get("precision", 2))
        return round(self.rng.uniform(lower, upper), precision)


class PercentageColumnGenerator(BaseColumnGenerator):
    """Generate percentage strings."""

    def __init__(self, rng: random.Random) -> None:
        super().__init__(dtype="percentage", rng=rng)

    def _generate_value(self, column: ColumnSchema, row_index: int) -> str:
        precision = int(column.metadata.get("precision", 1))
        value = round(self.rng.uniform(0, 100), precision)
        return f"{value:.{precision}f}%"


class FractionColumnGenerator(BaseColumnGenerator):
    """Generate fraction strings."""

    def __init__(self, rng: random.Random) -> None:
        super().__init__(dtype="fraction", rng=rng)

    def _generate_value(self, column: ColumnSchema, row_index: int) -> str:
        max_numerator = int(column.metadata.get("max_numerator", 20))
        max_denominator = int(column.metadata.get("max_denominator", 25))
        resolved_max_denominator = max(max_denominator, 2)
        resolved_max_numerator = min(max(max_numerator, 1), resolved_max_denominator - 1)
        numerator = self.rng.randint(1, max(resolved_max_numerator, 1))
        denominator = self.rng.randint(max(numerator + 1, 2), resolved_max_denominator)
        return f"{numerator}/{denominator}"


class DateColumnGenerator(BaseColumnGenerator):
    """Generate formatted date strings."""

    def __init__(self, rng: random.Random) -> None:
        super().__init__(dtype="date", rng=rng)

    def _generate_value(self, column: ColumnSchema, row_index: int) -> str:
        year = int(column.metadata.get("year", 2024))
        date_format = str(column.metadata.get("date_format", "%Y-%m-%d"))
        start_date = date(year, 1, 1)
        generated_date = start_date + timedelta(days=self.rng.randint(0, 364))
        return generated_date.strftime(date_format)


class IdentifierColumnGenerator(BaseColumnGenerator):
    """Generate identifier-like strings."""

    def __init__(self, rng: random.Random) -> None:
        super().__init__(dtype="identifier", rng=rng)

    def _generate_value(self, column: ColumnSchema, row_index: int) -> str:
        prefix = str(column.metadata.get("prefix", "REF"))
        start = int(column.metadata.get("start", 1000))
        return f"{prefix}-{start + row_index:05d}"


class AlphanumericCodeColumnGenerator(BaseColumnGenerator):
    """Generate alphanumeric reference codes."""

    def __init__(self, rng: random.Random) -> None:
        super().__init__(dtype="alphanumeric_code", rng=rng)

    def _generate_value(self, column: ColumnSchema, row_index: int) -> str:
        segments = tuple(column.metadata.get("segments", (3, 3)))
        separator = str(column.metadata.get("separator", "-"))
        alphabet = string.ascii_uppercase + string.digits
        parts = [
            "".join(self.rng.choice(alphabet) for _ in range(int(segment_length)))
            for segment_length in segments
        ]
        return separator.join(parts)


class SymbolicMixedColumnGenerator(BaseColumnGenerator):
    """Generate mixed symbolic strings."""

    def __init__(self, rng: random.Random) -> None:
        super().__init__(dtype="symbolic_mixed", rng=rng)

    def _generate_value(self, column: ColumnSchema, row_index: int) -> str:
        symbols = str(column.metadata.get("symbols", "@#"))
        left_symbol = self.rng.choice(symbols)
        right_symbol = self.rng.choice(symbols)
        letters = "".join(self.rng.choice(string.ascii_uppercase) for _ in range(2))
        digits = f"{self.rng.randint(0, 999):03d}"
        return f"{left_symbol}{letters}-{digits}{right_symbol}"


def build_column_generator(column: ColumnSchema, seed: int) -> BaseColumnGenerator:
    """Return a generator instance matching the schema dtype."""

    rng = random.Random(seed)
    generators: dict[str, type[BaseColumnGenerator]] = {
        "text_short": TextShortColumnGenerator,
        "text_long": TextLongColumnGenerator,
        "integer": IntegerColumnGenerator,
        "decimal": DecimalColumnGenerator,
        "percentage": PercentageColumnGenerator,
        "fraction": FractionColumnGenerator,
        "date": DateColumnGenerator,
        "identifier": IdentifierColumnGenerator,
        "alphanumeric_code": AlphanumericCodeColumnGenerator,
        "symbolic_mixed": SymbolicMixedColumnGenerator,
    }
    generator_cls = generators.get(column.dtype, TextShortColumnGenerator)
    return generator_cls(rng)
