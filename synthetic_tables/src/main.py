"""Entry point for the final synthetic tables pipeline."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from config import PipelineConfig, build_default_config
from exporters.format_exporter import FormatExporter
from generators.schema_generator import SchemaGenerator
from generators.table_generator import TableGenerator
from metadata.metadata_writer import MetadataWriter
from renderers.pdf_renderer import PDFRenderer
from renderers.pdf_to_image import PDFToImageConverter
from styles.style_sampler import StyleSampler, build_style_id
from utils.ids import make_sample_id
from utils.seed import set_global_seed

SUPPORTED_SOURCE_FORMATS: tuple[str, ...] = ("html", "latex", "markdown")


def generate_visual_samples(config: PipelineConfig) -> None:
    """Run the full pipeline from base tables to page images."""

    settings = config.settings
    config.prepare_workspace()
    set_global_seed(settings.seed)

    schema_generator = SchemaGenerator(
        min_columns=settings.min_cols,
        max_columns=settings.max_cols,
        min_rows=settings.min_rows,
        max_rows=settings.max_rows,
    )
    table_generator = TableGenerator(schema_generator=schema_generator)
    style_sampler = StyleSampler(base_seed=settings.seed)
    format_exporter = FormatExporter(style_sampler=style_sampler)
    metadata_writer = MetadataWriter(
        tables_metadata_path=config.paths.tables_metadata_path,
        samples_metadata_path=config.paths.samples_metadata_path,
    )
    pdf_renderer = PDFRenderer()
    pdf_to_image_converter = PDFToImageConverter()

    metadata_writer.reset_tables_metadata()
    metadata_writer.reset_samples_metadata()

    _print_configuration(config)

    generated_tables = schema_generator.generate_batch(
        table_count=settings.table_count,
        seed=settings.seed,
    )

    sample_counter = 0
    sample_breakdown: Counter[str] = Counter()

    for table_index, schema in enumerate(generated_tables, start=1):
        table = table_generator.generate_from_schema(schema)
        print(
            f"[table {table_index}/{settings.table_count}] "
            f"{table.name} -> {table.n_rows} rows x {table.n_cols} cols"
        )

        schema_path = schema_generator.save_schema(
            schema=schema,
            output_path=config.paths.schemas_dir / f"{schema.name}.json",
        )
        csv_path = format_exporter.export(
            table=table,
            output_path=config.paths.base_csv_dir / f"{schema.name}.csv",
            format_name="csv",
        )
        xlsx_path = format_exporter.export(
            table=table,
            output_path=config.paths.base_xlsx_dir / f"{schema.name}.xlsx",
            format_name="xlsx",
        )
        metadata_writer.write_table_metadata(
            table=table,
            csv_path=csv_path,
            xlsx_path=xlsx_path,
            schema_path=schema_path,
        )

        for source_format in settings.source_formats:
            for visual_version in range(1, settings.visual_versions + 1):
                version_label = f"v{visual_version:02d}"
                style_key = f"{table.table_id}:{source_format}:{version_label}"
                style = style_sampler.sample(source_format, style_key)
                style_id = build_style_id(source_format, style)
                # for testing/debugging
                if source_format != "latex":  
                    continue    
                rendered_source_path = _rendered_source_path(
                    config=config,
                    source_format=source_format,
                    table_name=table.name,
                    version_label=version_label,
                )
                format_exporter.export(
                    table=table,
                    output_path=rendered_source_path,
                    format_name=source_format,
                    style=style,
                )

                pdf_path = _rendered_pdf_path(
                    config=config,
                    source_format=source_format,
                    table_name=table.name,
                    version_label=version_label
                )
                pdf_result = pdf_renderer.render(
                    source_path=rendered_source_path,
                    output_path=pdf_path,
                    source_format=source_format,
                )
                print(
                    f"  - {source_format}/{version_label} -> PDF "
                    f"({pdf_result.pages} page(s), renderer={pdf_result.renderer})"
                )

                for dpi in settings.dpis:
                    sample_counter += 1
                    sample_id = make_sample_id(table.table_id, sample_counter)
                    image_output_dir = config.paths.rendered_images_dir / sample_id
                    image_result = pdf_to_image_converter.convert(
                        pdf_path=pdf_result.pdf_path,
                        output_dir=image_output_dir,
                        dpi=dpi,
                    )
                    metadata_writer.write_sample_metadata(
                        sample_id=sample_id,
                        table_id=table.table_id,
                        visual_version=version_label,
                        source_format=source_format,
                        renderer=pdf_result.renderer,
                        style_id=style_id,
                        font_family=style.font_family,
                        font_size_pt=style.font_size_pt,
                        dpi=dpi,
                        pages=image_result.pages,
                        page_image_paths=image_result.page_image_paths,
                        pdf_path=pdf_result.pdf_path,
                        csv_path=csv_path,
                        xlsx_path=xlsx_path,
                        n_rows=table.n_rows,
                        n_cols=table.n_cols,
                    )
                    sample_breakdown[f"{source_format}@{dpi}dpi"] += 1

    print("")
    print("Pipeline concluido com sucesso.")
    print(f"- tabelas_base: {settings.table_count}")
    print(f"- amostras_visuais: {sample_counter}")
    print(f"- tables_jsonl: {config.paths.tables_metadata_path}")
    print(f"- samples_jsonl: {config.paths.samples_metadata_path}")
    for label, count in sorted(sample_breakdown.items()):
        print(f"- {label}: {count} amostras")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Generate synthetic tables and visual samples end-to-end.",
    )
    parser.add_argument("--table-count", type=int, help="Number of base tables to generate.")
    parser.add_argument("--visual-versions", type=int, help="Number of style variants per source format.")
    parser.add_argument("--seed", type=int, help="Global seed for deterministic generation.")
    parser.add_argument("--min-rows", type=int, help="Minimum number of rows per table.")
    parser.add_argument("--max-rows", type=int, help="Maximum number of rows per table.")
    parser.add_argument("--min-cols", type=int, help="Minimum number of columns per table.")
    parser.add_argument("--max-cols", type=int, help="Maximum number of columns per table.")
    parser.add_argument(
        "--dpis",
        nargs="+",
        type=int,
        help="One or more target DPI values, for example: --dpis 100 300",
    )
    parser.add_argument(
        "--source-formats",
        nargs="+",
        choices=SUPPORTED_SOURCE_FORMATS,
        help="Rendered source formats to turn into PDF samples.",
    )
    return parser.parse_args()


def build_runtime_config(args: argparse.Namespace) -> PipelineConfig:
    """Build the runtime config from CLI arguments."""

    config = build_default_config()
    overrides: dict[str, object] = {}

    if args.table_count is not None:
        overrides["table_count"] = args.table_count
    if args.visual_versions is not None:
        overrides["visual_versions"] = args.visual_versions
    if args.seed is not None:
        overrides["seed"] = args.seed
    if args.min_rows is not None:
        overrides["min_rows"] = args.min_rows
    if args.max_rows is not None:
        overrides["max_rows"] = args.max_rows
    if args.min_cols is not None:
        overrides["min_cols"] = args.min_cols
    if args.max_cols is not None:
        overrides["max_cols"] = args.max_cols
    if args.dpis:
        overrides["dpis"] = tuple(dict.fromkeys(args.dpis))
    if args.source_formats:
        overrides["source_formats"] = tuple(dict.fromkeys(args.source_formats))

    if overrides:
        config = config.with_settings(**overrides)
    return config


def _rendered_source_path(
    config: PipelineConfig,
    source_format: str,
    table_name: str,
    version_label: str,
) -> Path:
    """Resolve the rendered intermediate output path for one visual version."""

    directory_map = {
        "html": config.paths.rendered_html_dir,
        "latex": config.paths.rendered_latex_dir,
        "markdown": config.paths.rendered_markdown_dir,
    }
    suffix_map = {
        "html": ".html",
        "latex": ".tex",
        "markdown": ".md",
    }
    return directory_map[source_format] / f"{table_name}__{version_label}{suffix_map[source_format]}"


def _rendered_pdf_path(
    config: PipelineConfig,
    source_format: str,
    table_name: str,
    version_label: str,
) -> Path:
    """Resolve the rendered PDF path and include the sampled layout/style family."""
    
    return config.paths.rendered_pdf_dir / f"{table_name}__{source_format}__{version_label}.pdf"


def _print_configuration(config: PipelineConfig) -> None:
    """Print a readable summary of the current pipeline configuration."""

    settings = config.settings
    print("Iniciando pipeline synthetic_tables.")
    print(f"- stage: {config.current_stage}")
    print(f"- seed: {settings.seed}")
    print(f"- table_count: {settings.table_count}")
    print(f"- visual_versions: {settings.visual_versions}")
    print(f"- row_range: {settings.min_rows}-{settings.max_rows}")
    print(f"- col_range: {settings.min_cols}-{settings.max_cols}")
    print(f"- dpis: {', '.join(str(dpi) for dpi in settings.dpis)}")
    print(f"- source_formats: {', '.join(settings.source_formats)}")
    print("")


def main() -> None:
    """Parse CLI arguments and run the pipeline."""

    args = parse_args()
    config = build_runtime_config(args)
    generate_visual_samples(config)


if __name__ == "__main__":
    main()
