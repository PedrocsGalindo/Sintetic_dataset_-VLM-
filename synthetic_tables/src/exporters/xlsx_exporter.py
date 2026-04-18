"""XLSX exporting utilities for base tables."""

from __future__ import annotations

from html import escape
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from generators.table_generator import GeneratedTable
from utils.io import ensure_parent_dir

try:
    from openpyxl import Workbook
except ImportError:  # pragma: no cover
    Workbook = None


class XLSXExporter:
    """Export generated base tables to XLSX."""

    def export(self, table: GeneratedTable, output_path: Path) -> Path:
        """Write one generated table to XLSX."""

        ensure_parent_dir(output_path)
        if Workbook is None:
            return self._export_with_zipfile(table, output_path)

        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = table.name[:31] or "table"
        worksheet.append(table.columns)
        for row in table.row_values():
            worksheet.append(row)
        workbook.save(output_path)
        return output_path

    def _export_with_zipfile(self, table: GeneratedTable, output_path: Path) -> Path:
        """Write a minimal XLSX file without external dependencies."""

        sheet_name = (table.name[:31] or "table").replace("&", "and")
        with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", self._content_types_xml())
            archive.writestr("_rels/.rels", self._root_rels_xml())
            archive.writestr("xl/workbook.xml", self._workbook_xml(sheet_name))
            archive.writestr("xl/_rels/workbook.xml.rels", self._workbook_rels_xml())
            archive.writestr("xl/worksheets/sheet1.xml", self._worksheet_xml(table))
        return output_path

    @staticmethod
    def _content_types_xml() -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>"
        )

    @staticmethod
    def _root_rels_xml() -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="xl/workbook.xml"/>'
            "</Relationships>"
        )

    @staticmethod
    def _workbook_xml(sheet_name: str) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            "<sheets>"
            f'<sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/>'
            "</sheets>"
            "</workbook>"
        )

    @staticmethod
    def _workbook_rels_xml() -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        )

    def _worksheet_xml(self, table: GeneratedTable) -> str:
        rows_xml: list[str] = []
        worksheet_rows = [table.columns, *table.row_values()]

        for row_index, row in enumerate(worksheet_rows, start=1):
            cells_xml: list[str] = []
            for column_index, value in enumerate(row, start=1):
                cell_reference = f"{self._column_letter(column_index)}{row_index}"
                cells_xml.append(self._cell_xml(cell_reference, value))
            rows_xml.append(f'<row r="{row_index}">{"".join(cells_xml)}</row>')

        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{''.join(rows_xml)}</sheetData>"
            "</worksheet>"
        )

    @staticmethod
    def _cell_xml(cell_reference: str, value: object) -> str:
        if value is None:
            return f'<c r="{cell_reference}" t="inlineStr"><is><t></t></is></c>'
        if isinstance(value, (int, float)):
            return f'<c r="{cell_reference}"><v>{value}</v></c>'
        return (
            f'<c r="{cell_reference}" t="inlineStr">'
            f"<is><t>{escape(str(value))}</t></is>"
            "</c>"
        )

    @staticmethod
    def _column_letter(index: int) -> str:
        letters: list[str] = []
        current = index
        while current > 0:
            current, remainder = divmod(current - 1, 26)
            letters.append(chr(65 + remainder))
        return "".join(reversed(letters))
