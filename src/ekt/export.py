"""Typed spreadsheet exports with formula-safe text and calculation metadata."""
import io
import json
import re
import pandas as pd
from openpyxl.styles import Font, PatternFill, Alignment

_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_UNREPRESENTABLE_XML = re.compile(r"[\ud800-\udfff\ufffe\uffff]")


def safe_text(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    if isinstance(value, str) and value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def sanitized(frame):
    result = frame.copy()
    for col in result:
        if not pd.api.types.is_numeric_dtype(result[col]):
            result[col] = result[col].map(safe_text)
    return result


def _xlsx_text(value, location):
    if not isinstance(value, str):
        return value
    unsupported = _UNREPRESENTABLE_XML.search(value)
    if unsupported:
        raise ValueError(
            f"XLSX: {location}: символ U+{ord(unsupported.group()):04X} "
            "не поддерживается XML"
        )
    value = _ILLEGAL_XML.sub(
        lambda match: f"\\x{ord(match.group()):02x}", safe_text(value)
    )
    if len(value) > 32767:
        raise ValueError(
            f"XLSX: {location}: "
            "текст длиннее поддерживаемых Excel 32767 символов"
        )
    return value


def _xlsx_frame(frame, sheet_name):
    """Prepare an export-only copy that OpenXML can represent without data loss."""
    result = frame.copy()
    result.columns = [
        _xlsx_text(column, f"{sheet_name}, заголовок колонки {column_number}")
        for column_number, column in enumerate(frame.columns, 1)
    ]
    for column_number in range(1, len(result.columns) + 1):
        column = result.iloc[:, column_number - 1]
        if pd.api.types.is_numeric_dtype(column):
            continue
        result.isetitem(column_number - 1, [
            _xlsx_text(value, f"{sheet_name}, колонка {column_number}, строка {excel_row}")
            for excel_row, value in enumerate(column, 2)
        ])
    return result


def csv_bytes(frame, separator=";"):
    if separator not in [";", ","]:
        raise ValueError("Недопустимый разделитель CSV")
    return sanitized(frame).to_csv(index=False, sep=separator, lineterminator="\r\n").encode("utf-8-sig")


def xlsx_bytes(frame, metadata=None):
    buffer = io.BytesIO()
    orders = _xlsx_frame(frame, "Orders")
    meta = pd.DataFrame([{"parameter": k, "value": json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list)) else str(v)} for k, v in (metadata or {}).items()], dtype=object)
    meta = _xlsx_frame(meta, "Calculation")
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        orders.to_excel(writer, sheet_name="Orders", index=False)
        meta.to_excel(writer, sheet_name="Calculation", index=False)
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            sheet.auto_filter.ref = sheet.dimensions
            for cell in sheet[1]:
                cell.fill = PatternFill("solid", fgColor="17695B")
                cell.font = Font(color="FFFFFF", bold=True)
                cell.alignment = Alignment(wrap_text=True)
            for column in sheet.columns:
                header = column[0].value
                sheet.column_dimensions[column[0].column_letter].width = 22 if header not in ["explanation", "data_warnings", "assumptions"] else 64
                if header in ["sku_1c", "supplier_sku", "supplier_id", "warehouse_scope"]:
                    for cell in column[1:]:
                        cell.number_format = "@"
                        if cell.value is not None:
                            cell.value = str(cell.value)
            sheet.sheet_view.showGridLines = False
    return buffer.getvalue()
