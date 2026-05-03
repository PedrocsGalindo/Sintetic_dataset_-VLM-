"""Build a clean training/evaluation dataset from generated pipeline artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path
from typing import Any

FILTER_SOURCE_FORMAT = [
    "markdown",
]

REQUIRED_METADATA_COLUMNS = [
#    "sample_id",
    "base_table_id",
    "source_format",
    "visual_version",
#    "renderer",
    "dpi",
    "page_number",
    "image_path",
    "base_table_path",
    "font_family",
    "font_size_pt",
    "style_id",
]

OPTIONAL_STYLE_COLUMNS = [
    "template_name",
    "alignment_profile",
    "header_background",
    "border_color",
    "background_color",
    "accent_color",
    "table_width",
    "zebra_striping",
]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load a JSONL file into a list of dictionaries."""

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {path} at line {line_number}: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"Expected a JSON object in {path} at line {line_number}.")
            records.append(record)
    return records


def ensure_clean_dir(path: Path) -> None:
    """Remove an existing directory and recreate it empty."""

    if path.exists():
        if not path.is_dir():
            raise NotADirectoryError(f"Output path exists but is not a directory: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def dataset_relative(path: Path, dataset_dir: Path) -> str:
    """Return a POSIX-style path relative to the dataset root."""

    return path.resolve().relative_to(dataset_dir.resolve()).as_posix()


def copy_base_tables(
    data_dir: Path,
    dataset_dir: Path,
    table_records: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Copy base CSV files and build lookup maps for rendered samples."""

    output_dir = dataset_dir / "base_tables"
    output_dir.mkdir(parents=True, exist_ok=True)

    table_lookup: dict[str, dict[str, str]] = {}
    copied_paths: dict[str, str] = {}

    for record in table_records:
        table_id = str(record.get("table_id") or "").strip()
        csv_path = _resolve_existing_path(record.get("csv_path"), data_dir)
        base_table_id = str(record.get("name") or (csv_path.stem if csv_path else table_id)).strip()
        if not table_id or not base_table_id:
            continue

        if csv_path:
            relative_path = _copy_base_table_csv(csv_path, base_table_id, output_dir, dataset_dir)
            copied_paths[base_table_id] = relative_path

        table_lookup[table_id] = {
            "base_table_id": base_table_id,
            "base_table_path": copied_paths.get(base_table_id, f"base_tables/{base_table_id}.csv"),
        }

    csv_sources = sorted((data_dir / "base_tables" / "csv").glob("*.csv"))
    if not csv_sources:
        csv_sources = sorted((data_dir / "base_tables").glob("*.csv"))

    for csv_path in csv_sources:
        base_table_id = csv_path.stem
        copied_paths[base_table_id] = _copy_base_table_csv(
            csv_path=csv_path,
            base_table_id=base_table_id,
            output_dir=output_dir,
            dataset_dir=dataset_dir,
        )

    for lookup in table_lookup.values():
        base_table_id = lookup["base_table_id"]
        if base_table_id in copied_paths:
            lookup["base_table_path"] = copied_paths[base_table_id]

    if not copied_paths:
        raise FileNotFoundError(f"No base CSV files found under {data_dir / 'base_tables'}.")

    return copied_paths, table_lookup


def copy_images_and_build_metadata(
    samples: list[dict[str, Any]],
    data_dir: Path,
    dataset_dir: Path,
    copied_base_tables: dict[str, str],
    table_lookup: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    """Copy rendered page images into the final dataset and return clean metadata rows."""

    rows: list[dict[str, Any]] = []
    used_destinations: set[Path] = set()

    for sample in samples:
        image_paths = sample.get("page_image_paths")
        if not isinstance(image_paths, list) or not image_paths:
            raise ValueError(f"Sample {sample.get('sample_id')} does not contain page_image_paths.")

        table_id = str(sample.get("table_id") or "").strip()
        source_format = str(sample.get("source_format") or "").strip()
        if source_format.lower() in FILTER_SOURCE_FORMAT:
            continue
        visual_version = str(sample.get("visual_version") or "").strip()
        dpi = sample.get("dpi")
        sample_id = str(sample.get("sample_id") or "").strip()

        if not table_id or not source_format or not visual_version or not dpi or not sample_id:
            raise ValueError(f"Sample has missing required metadata: {sample}")

        base_table_id = _base_table_id_for_sample(sample, table_lookup, data_dir)
        base_table_path = _base_table_path_for_sample(
            sample=sample,
            base_table_id=base_table_id,
            copied_base_tables=copied_base_tables,
            dataset_dir=dataset_dir,
            data_dir=data_dir,
        )
        variant_dir = f"{source_format}_{visual_version}_{dpi}dpi"
        output_dir = dataset_dir / "images" / _safe_segment(base_table_id) / _safe_segment(variant_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        for page_index, raw_image_path in enumerate(image_paths, start=1):
            source_image = _resolve_existing_path(raw_image_path, data_dir)
            if source_image is None:
                raise FileNotFoundError(
                    f"Image for sample {sample_id}, page {page_index}, was not found: {raw_image_path}"
                )

            destination = output_dir / f"page_{page_index:03d}{source_image.suffix.lower() or '.png'}"
            if destination in used_destinations or destination.exists():
                raise FileExistsError(
                    "Multiple samples would write to the same dataset image path: "
                    f"{dataset_relative(destination, dataset_dir)}"
                )
            shutil.copy2(source_image, destination)
            used_destinations.add(destination)

            row = {
                "sample_id": sample_id,
                "base_table_id": base_table_id,
                "source_format": source_format,
                "visual_version": visual_version,
                "renderer": _csv_value(sample.get("renderer")),
                "dpi": _csv_value(dpi),
                "page_number": page_index,
                "image_path": dataset_relative(destination, dataset_dir),
                "base_table_path": base_table_path,
                "font_family": _csv_value(sample.get("font_family")),
                "font_size_pt": _csv_value(sample.get("font_size_pt")),
                "style_id": _csv_value(sample.get("style_id")),
            }
            for column in OPTIONAL_STYLE_COLUMNS:
                if column in sample:
                    row[column] = _csv_value(sample.get(column))
            rows.append(row)

    return rows


def write_metadata_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    """Write clean page-level dataset metadata."""

    optional_columns = [
        column
        for column in OPTIONAL_STYLE_COLUMNS
        if any(column in row and row[column] != "" for row in rows)
    ]
    fieldnames = REQUIRED_METADATA_COLUMNS + optional_columns

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Build a clean dataset directory from existing synthetic table artifacts.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Pipeline data directory. Defaults to ./data, or ./synthetic_tables/data when present.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Dataset output directory. Defaults to <data-dir>/dataset.",
    )
    parser.add_argument(
        "--samples-metadata",
        type=Path,
        help="Path to samples JSONL metadata. Defaults to <data-dir>/metadata/samples.jsonl.",
    )
    parser.add_argument(
        "--tables-metadata",
        type=Path,
        help="Path to tables JSONL metadata. Defaults to <data-dir>/metadata/tables.jsonl when present.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Delete and rebuild the output dataset directory if it already exists.",
    )
    return parser.parse_args()


def main() -> None:
    """Build the final dataset."""

    args = parse_args()
    data_dir = _resolve_data_dir(args.data_dir)
    dataset_dir = (args.output_dir or data_dir / "dataset").resolve()
    _validate_output_dir(dataset_dir=dataset_dir, data_dir=data_dir)

    samples_metadata_path = _resolve_metadata_path(
        explicit_path=args.samples_metadata,
        data_dir=data_dir,
        preferred_name="samples.jsonl",
        fallback_pattern="*samples*.jsonl",
        required=True,
    )
    tables_metadata_path = _resolve_metadata_path(
        explicit_path=args.tables_metadata,
        data_dir=data_dir,
        preferred_name="tables.jsonl",
        fallback_pattern="*tables*.jsonl",
        required=False,
    )

    if dataset_dir.exists() and not args.overwrite:
        raise FileExistsError(
            f"Output directory already exists: {dataset_dir}. "
            "Run again with --overwrite to rebuild it."
        )

    samples = load_jsonl(samples_metadata_path)
    table_records = load_jsonl(tables_metadata_path) if tables_metadata_path else []

    ensure_clean_dir(dataset_dir)
    copied_base_tables, table_lookup = copy_base_tables(
        data_dir=data_dir,
        dataset_dir=dataset_dir,
        table_records=table_records,
    )
    metadata_rows = copy_images_and_build_metadata(
        samples=samples,
        data_dir=data_dir,
        dataset_dir=dataset_dir,
        copied_base_tables=copied_base_tables,
        table_lookup=table_lookup,
    )
    write_metadata_csv(metadata_rows, dataset_dir / "metadata.csv")

    print(f"Dataset built at: {dataset_dir}")
    print(f"- base tables: {len(copied_base_tables)}")
    print(f"- samples: {len(samples)}")
    print(f"- image pages: {len(metadata_rows)}")
    print(f"- metadata: {dataset_dir / 'metadata.csv'}")


def _copy_base_table_csv(
    csv_path: Path,
    base_table_id: str,
    output_dir: Path,
    dataset_dir: Path,
) -> str:
    destination = output_dir / f"{_safe_segment(base_table_id)}.csv"
    shutil.copy2(csv_path, destination)
    return dataset_relative(destination, dataset_dir)


def _base_table_id_for_sample(
    sample: dict[str, Any],
    table_lookup: dict[str, dict[str, str]],
    data_dir: Path,
) -> str:
    table_id = str(sample.get("table_id") or "").strip()
    if table_id in table_lookup:
        return table_lookup[table_id]["base_table_id"]

    csv_path = _resolve_existing_path(sample.get("csv_path"), data_dir)
    if csv_path:
        return csv_path.stem
    return table_id


def _base_table_path_for_sample(
    sample: dict[str, Any],
    base_table_id: str,
    copied_base_tables: dict[str, str],
    dataset_dir: Path,
    data_dir: Path,
) -> str:
    if base_table_id in copied_base_tables:
        return copied_base_tables[base_table_id]

    csv_path = _resolve_existing_path(sample.get("csv_path"), data_dir)
    if csv_path is None:
        raise FileNotFoundError(f"Base CSV for sample {sample.get('sample_id')} was not found.")

    output_dir = dataset_dir / "base_tables"
    output_dir.mkdir(parents=True, exist_ok=True)
    relative_path = _copy_base_table_csv(csv_path, base_table_id, output_dir, dataset_dir)
    copied_base_tables[base_table_id] = relative_path
    return relative_path


def _resolve_data_dir(path: Path | None) -> Path:
    candidates = [path] if path else [Path("data"), Path("synthetic_tables") / "data"]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate.resolve()

    if path == Path("data") and (Path("synthetic_tables") / "data").exists():
        return (Path("synthetic_tables") / "data").resolve()

    attempted = ", ".join(str(candidate) for candidate in candidates if candidate)
    raise FileNotFoundError(f"Data directory not found. Tried: {attempted}")


def _resolve_metadata_path(
    explicit_path: Path | None,
    data_dir: Path,
    preferred_name: str,
    fallback_pattern: str,
    required: bool,
) -> Path | None:
    if explicit_path:
        path = explicit_path.resolve()
        if not path.exists():
            raise FileNotFoundError(f"Metadata file not found: {path}")
        return path

    preferred_path = data_dir / "metadata" / preferred_name
    if preferred_path.exists():
        return preferred_path.resolve()

    matches = sorted((data_dir / "metadata").glob(fallback_pattern))
    if matches:
        return matches[0].resolve()

    if required:
        raise FileNotFoundError(f"Metadata file not found: {preferred_path}")
    return None


def _resolve_existing_path(raw_path: Any, data_dir: Path) -> Path | None:
    if raw_path is None:
        return None

    path = Path(str(raw_path))
    if path.exists():
        return path.resolve()

    normalized = str(raw_path).replace("\\", "/")
    if "/data/" in normalized:
        suffix = normalized.split("/data/", 1)[1]
        candidate = data_dir / Path(suffix)
        if candidate.exists():
            return candidate.resolve()

    candidate = data_dir / path
    if candidate.exists():
        return candidate.resolve()

    if path.name:
        for base_dir in (
            data_dir / "base_tables" / "csv",
            data_dir / "rendered" / "images",
            data_dir / "rendered" / "pdf",
        ):
            matches = list(base_dir.rglob(path.name)) if base_dir.exists() else []
            if matches:
                return matches[0].resolve()

    return None


def _validate_output_dir(dataset_dir: Path, data_dir: Path) -> None:
    data_dir = data_dir.resolve()
    dataset_dir = dataset_dir.resolve()

    if dataset_dir == data_dir:
        raise ValueError("--output-dir cannot be the same as --data-dir.")
    if data_dir not in dataset_dir.parents:
        raise ValueError("--output-dir must be inside --data-dir.")


def _safe_segment(value: str) -> str:
    return value.replace("/", "_").replace("\\", "_").strip()


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=True, sort_keys=True)
    return str(value)


if __name__ == "__main__":
    main()
