"""Read canonical CSV ZIPs or workbooks, without extracting files to disk."""
from __future__ import annotations
import io
from pathlib import PurePosixPath
import zipfile
import pandas as pd
from .schema import Bundle, SCHEMAS, normalize, validate

MAX_BYTES = 100 * 1024 * 1024


def parse_csv(data: bytes):
    text = data.decode("utf-8-sig")
    # All identifiers start as text; no numeric SKU coercion.
    separator = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
    return pd.read_csv(io.StringIO(text), sep=separator, dtype="string", keep_default_na=False, na_values=[""])


def read_canonical(data: bytes, filename: str, mode="manual"):
    if len(data) > MAX_BYTES:
        raise ValueError("Файл больше 100 МБ")
    tables = {}
    extension = PurePosixPath(filename).suffix.lower()
    if extension == ".zip":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            files = [x for x in archive.infolist() if not x.is_dir()]
            if len(files) > 100 or sum(x.file_size for x in files) > MAX_BYTES:
                raise ValueError("Распакованный архив превышает лимит 100 МБ / 100 файлов")
            for entry in files:
                path = PurePosixPath(entry.filename.replace("\\", "/"))
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("Недопустимый путь в ZIP")
                if path.suffix.lower() != ".csv" or path.stem not in SCHEMAS:
                    continue
                if path.stem in tables:
                    raise ValueError(f"Повтор таблицы {path.stem}")
                tables[path.stem] = parse_csv(archive.read(entry))
    elif extension == ".xlsx":
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            if sum(x.file_size for x in package.infolist()) > MAX_BYTES:
                raise ValueError("XLSX превышает лимит распакованного размера")
        book = pd.ExcelFile(io.BytesIO(data), engine="openpyxl")
        for sheet in book.sheet_names:
            if sheet in SCHEMAS:
                tables[sheet] = pd.read_excel(book, sheet_name=sheet, dtype="string")
    elif extension == ".csv" and PurePosixPath(filename).stem in SCHEMAS:
        tables[PurePosixPath(filename).stem] = parse_csv(data)
    else:
        raise ValueError("Нужен ZIP с каноническими CSV или XLSX с именами листов из контракта")
    if not tables:
        raise ValueError("Канонические таблицы не найдены. Для отчётов партнёра выберите отдельный режим импорта.")
    for name, frame in tables.items():
        if "source_file" not in frame:
            frame["source_file"] = filename
        if "source_sheet" not in frame:
            frame["source_sheet"] = name
        if mode == "partner" and "data_mode" in frame and frame["data_mode"].eq("synthetic").any():
            raise ValueError("Синтетический файл нельзя загрузить как данные партнёра")
    bundle = normalize(Bundle(tables, [], mode))
    # Editing incomplete bundles is permitted; the calculation validates them later.
    return bundle


def merge_tables(base, addition):
    result = base.copy()
    for name, frame in addition.tables.items():
        if not frame.empty:
            result.tables[name] = frame.copy()
    result.notes.extend(addition.notes)
    return normalize(result)
