"""Identifier helpers for generated tables and samples."""

from __future__ import annotations

import re
import uuid


def slugify(value: str) -> str:
    """Convert free-form text into a filesystem-friendly slug."""

    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    return normalized.strip("_") or "item"


def make_id(prefix: str) -> str:
    """Build a compact identifier with a prefix."""

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def make_sample_id(table_id: str, sample_index: int) -> str:
    """Build a deterministic sample id for rendered artifacts."""

    return f"{slugify(table_id)}_sample_{sample_index:04d}"
