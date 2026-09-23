"""Read canonical CSV ZIPs or workbooks, without extracting files to disk."""
from __future__ import annotations
import io
from pathlib import PurePosixPath
import posixpath
import re
import zipfile
import pandas as pd
from openpyxl.utils.cell import coordinate_to_tuple, range_boundaries
from openpyxl.xml.functions import iterparse
from .schema import Bundle, REQUIRED, SCHEMAS, normalize

MAX_BYTES = 100 * 1024 * 1024
MAX_EXPANDED_BYTES = 200 * 1024 * 1024
MAX_FILES = 100
MAX_ROWS = 500_000
MAX_CELLS = 5_000_000
# Bundle fills omitted tables with empty frames. Keep import presence separately
# from row data; pandas preserves attrs through Bundle.copy() and normalize().
_CANONICAL_TABLE = "_ekt_canonical_table"


class ImportBudget:
    """Cumulative limits for one import operation; useful for test-sized budgets."""

    def __init__(self, *, max_bytes=MAX_BYTES, max_expanded_bytes=MAX_EXPANDED_BYTES,
                 max_files=MAX_FILES, max_rows=MAX_ROWS, max_cells=MAX_CELLS):
        self.max_bytes = max_bytes
        self.max_expanded_bytes = max_expanded_bytes
        self.max_files = max_files
        self.max_rows = max_rows
        self.max_cells = max_cells
        self.bytes = self.expanded_bytes = self.files = self.rows = self.cells = 0

    @staticmethod
    def _check(label, value, limit):
        if value > limit:
            raise ValueError(f"Импорт превышает общий лимит: {label} {value} > {limit}")

    def add_bytes(self, count):
        self.bytes += count
        self._check("входных байтов", self.bytes, self.max_bytes)

    def add_expanded(self, count):
        self.expanded_bytes += count
        self._check("распакованных байтов", self.expanded_bytes, self.max_expanded_bytes)

    def add_files(self, count):
        self.files += count
        self._check("файлов", self.files, self.max_files)

    def add_row(self, cells):
        self.rows += 1
        self.cells += cells
        self._check("строк", self.rows, self.max_rows)
        self._check("ячеек", self.cells, self.max_cells)


def _count_csv(text, separator, budget):
    # Count records without allocating their fields or changing csv's global
    # field_size_limit (whose default rejects otherwise valid long text).
    fields, row_start, previous = 1, 0, 0
    quoted, field_start, closing_quote = False, True, False
    rows = columns = cells = 0

    def count_row(width):
        nonlocal rows, columns, cells
        rows += 1
        columns = max(columns, width)
        # pandas pads short records to the widest row/header.
        padded_cells = rows * columns
        budget.add_row(padded_cells - cells)
        cells = padded_cells

    for match in re.finditer(f'["\\r\\n{separator}]', text):
        token, position = match.group(), match.start()
        if position > previous and not quoted:
            field_start, closing_quote = False, False
        if token == '"':
            if quoted:
                quoted, closing_quote = False, True
            elif field_start or closing_quote:
                quoted, closing_quote = True, False
            field_start = False
        elif not quoted:
            closing_quote = False
            if token == separator:
                fields += 1
                field_start = True
            else:
                if not (token == "\n" and position and text[position - 1] == "\r"):
                    count_row(fields if position > row_start else 0)
                fields, field_start, row_start = 1, True, match.end()
        previous = match.end()
    if row_start < len(text):
        count_row(fields)


def parse_csv(data: bytes, budget=None):
    text = data.decode("utf-8-sig")
    if not text.strip():
        raise ValueError("CSV не содержит заголовков; для очистки таблицы оставьте обязательные столбцы")
    # All identifiers start as text; no numeric SKU coercion.
    line_end = re.search(r"[\r\n]", text)
    first_line = text[:line_end.start()] if line_end else text
    separator = ";" if first_line.count(";") > first_line.count(",") else ","
    if budget is not None:
        _count_csv(text, separator, budget)
    return pd.read_csv(io.StringIO(text), sep=separator, dtype="string", keep_default_na=False, na_values=[""])


def _xml_elements(source):
    """Yield start tags and release finished elements instead of retaining XML."""
    parents = []
    for event, element in iterparse(source, events=("start", "end")):
        if event == "start":
            parents.append(element)
            yield element
        else:
            element.clear()
            parents.pop()
            if parents:
                parents[-1].remove(element)


def _worksheet_paths(package):
    # Worksheet targets need not live in xl/worksheets or use an .xml suffix.
    # Inspect relationships too, matching the paths an Excel reader can follow.
    paths = {entry.filename for entry in package.infolist()
             if PurePosixPath(entry.filename).parent.as_posix() == "xl/worksheets"
             and PurePosixPath(entry.filename).suffix.lower() == ".xml"}
    for entry in package.infolist():
        path = PurePosixPath(entry.filename)
        if path.parent.name != "_rels" or path.suffix != ".rels":
            continue
        with package.open(entry) as source:
            for element in _xml_elements(source):
                if not element.get("Type", "").endswith("/worksheet") or element.get("TargetMode") == "External":
                    continue
                target = element.get("Target", "")
                if target.startswith("/"):
                    paths.add(target.lstrip("/"))
                else:
                    paths.add(posixpath.normpath(posixpath.join(path.parent.parent.as_posix(), target)))
    return paths


def _count_workbook(data, budget):
    """Bound padded sheet dimensions before an Excel parser creates row tuples.

    Read all worksheet XML, including sheets not used by the adapter. Declared
    dimensions and actual coordinates both count: either can cause a parser to
    allocate blank rows/cells, even in an otherwise tiny compressed workbook.
    """
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        worksheet_paths = _worksheet_paths(package)
        for member in package.infolist():
            if member.filename not in worksheet_paths:
                continue
            rows = columns = current_row = current_column = 0
            with package.open(member) as source:
                for element in _xml_elements(source):
                    if element.tag == namespace + "dimension" and element.get("ref"):
                        _, _, end_column, end_row = range_boundaries(element.get("ref"))
                        rows, columns = max(rows, end_row or 0), max(columns, end_column or 0)
                    elif element.tag == namespace + "row":
                        current_row = int(element.get("r", current_row + 1))
                        current_column = 0
                        rows = max(rows, current_row)
                    elif element.tag == namespace + "c":
                        coordinate = element.get("r")
                        if coordinate:
                            cell_row, current_column = coordinate_to_tuple(coordinate)
                            rows = max(rows, cell_row)
                        else:
                            current_column += 1
                        columns = max(columns, current_column)
                    else:
                        continue
                    budget._check("строк", budget.rows + rows, budget.max_rows)
                    budget._check("ячеек", budget.cells + rows * columns, budget.max_cells)
            budget.rows += rows
            budget.cells += rows * columns


def read_canonical(data: bytes, filename: str, mode="manual", budget=None):
    budget = budget or ImportBudget()
    budget.add_bytes(len(data))
    if len(data) > MAX_BYTES:
        raise ValueError("Файл больше 100 МБ")
    tables = {}
    extension = PurePosixPath(filename).suffix.lower()
    if extension == ".zip":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            files = [x for x in archive.infolist() if not x.is_dir()]
            expanded = sum(x.file_size for x in files)
            if len(files) > MAX_FILES or expanded > MAX_BYTES:
                raise ValueError("Распакованный архив превышает лимит 100 МБ / 100 файлов")
            budget.add_files(len(files))
            budget.add_expanded(expanded)
            for entry in files:
                path = PurePosixPath(entry.filename.replace("\\", "/"))
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("Недопустимый путь в ZIP")
                if path.suffix.lower() != ".csv" or path.stem not in SCHEMAS:
                    continue
                if path.stem in tables:
                    raise ValueError(f"Повтор таблицы {path.stem}")
                tables[path.stem] = parse_csv(archive.read(entry), budget)
    elif extension == ".xlsx":
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            expanded = sum(x.file_size for x in package.infolist())
            if expanded > MAX_BYTES:
                raise ValueError("XLSX превышает лимит распакованного размера")
        budget.add_files(1)
        budget.add_expanded(expanded)
        _count_workbook(data, budget)
        with pd.ExcelFile(io.BytesIO(data), engine="openpyxl") as book:
            for sheet in book.sheet_names:
                if sheet in SCHEMAS:
                    tables[sheet] = pd.read_excel(book, sheet_name=sheet, dtype="string", keep_default_na=False, na_values=[""])
    elif extension == ".csv" and PurePosixPath(filename).stem in SCHEMAS:
        budget.add_files(1)
        tables[PurePosixPath(filename).stem] = parse_csv(data, budget)
    else:
        raise ValueError("Нужен ZIP с каноническими CSV или XLSX с именами листов из контракта")
    if not tables:
        raise ValueError("Канонические таблицы не найдены. Для отчётов партнёра выберите отдельный режим импорта.")
    for name, frame in tables.items():
        if frame.empty:
            missing = [column for column in REQUIRED[name] if column not in frame.columns]
            if missing:
                raise ValueError(f"{name}: для очистки пустой таблицы нужны заголовки: {', '.join(missing)}")
        frame.attrs[_CANONICAL_TABLE] = name
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
    """Replace nonempty tables and explicitly present empty canonical imports."""
    result = base.copy()
    for name, frame in addition.tables.items():
        if not frame.empty or frame.attrs.get(_CANONICAL_TABLE) == name:
            result.tables[name] = frame.copy()
    result.notes.extend(addition.notes)
    return normalize(result)
