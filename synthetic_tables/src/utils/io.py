"""Filesystem helpers for the synthetic tables project."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping


def ensure_dir(path: Path) -> Path:
    """Create a directory if it does not exist."""

    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_parent_dir(path: Path) -> Path:
    """Create the parent directory for a file path."""

    path.parent.mkdir(parents=True, exist_ok=True)
    return path.parent


def touch_file(path: Path, default_text: str = "") -> Path:
    """Create a file if it does not exist yet."""

    ensure_parent_dir(path)
    if not path.exists():
        path.write_text(default_text, encoding="utf-8")
    return path


def write_text_file(path: Path, content: str) -> Path:
    """Write UTF-8 text content to disk."""

    ensure_parent_dir(path)
    path.write_text(content, encoding="utf-8")
    return path


def append_jsonl(path: Path, record: Mapping[str, Any]) -> Path:
    """Append a single JSONL record to disk."""

    ensure_parent_dir(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(record), ensure_ascii=False) + "\n")
    return path


def ensure_project_layout(directories: Iterable[Path], files: Iterable[Path]) -> None:
    """Create the directory tree and placeholder files for stage 1."""

    for directory in directories:
        ensure_dir(directory)
    for file_path in files:
        touch_file(file_path)
