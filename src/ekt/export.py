"""Typed spreadsheet exports with formula-safe text and calculation metadata."""
import io
import json
import pandas as pd
from openpyxl.styles import Font, PatternFill, Alignment


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


def csv_bytes(frame, separator=";"):
    if separator not in [";", ","]:
        raise ValueError("Недопустимый разделитель CSV")
    return sanitized(frame).to_csv(index=False, sep=separator, lineterminator="\r\n").encode("utf-8-sig")


def xlsx_bytes(frame, metadata=None):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        sanitized(frame).to_excel(writer, sheet_name="Orders", index=False)
        meta = pd.DataFrame([{"parameter": k, "value": json.dumps(v, ensure_ascii=False, default=str) if isinstance(v, (dict, list)) else str(v)} for k, v in (metadata or {}).items()])
        sanitized(meta).to_excel(writer, sheet_name="Calculation", index=False)
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
