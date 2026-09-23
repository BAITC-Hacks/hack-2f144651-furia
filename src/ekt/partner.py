"""Conservative IEK/Systeme adapters based on the supplied schema audit.

Verified using synthetic workbooks shaped like the audit, not partner archives.
Unknown scope, units, formula caches and policy semantics remain visible.
"""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime, date
import io
from pathlib import PurePosixPath
import re
import zipfile
import pandas as pd
from openpyxl import load_workbook
from .schema import Bundle, normalize
from .ingest import MAX_BYTES

MONTHS = {"янв": 1, "фев": 2, "мар": 3, "апр": 4, "май": 5, "мая": 5, "июн": 6, "июл": 7, "авг": 8, "сен": 9, "окт": 10, "ноя": 11, "дек": 12}


def text(value):
    if value is None:
        return None
    if isinstance(value, (int, float)) and float(value).is_integer():
        return str(int(value))
    return str(value).strip() or None


def numeric(value):
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, str):
        value = value.replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        result = float(value)
        return result if pd.notna(result) else None
    except (ValueError, TypeError):
        return None


def month_value(value):
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return pd.Timestamp(value).to_period("M").start_time
    value = str(value or "").lower()
    year = re.search(r"\b(20\d{2})\b", value)
    month = next((number for stem, number in MONTHS.items() if stem in value), None)
    if year and month:
        return pd.Timestamp(int(year.group()), month, 1)
    match = re.fullmatch(r"\s*(20\d{2})[-./](\d{1,2})(?:[-./]\d{1,2})?\s*", value)
    if match:
        try:
            return pd.Timestamp(int(match[1]), int(match[2]), 1)
        except ValueError:
            return None
    match = re.fullmatch(r"\s*(?:\d{1,2}[./])?(\d{1,2})[./](20\d{2})\s*", value)
    if match:
        try:
            return pd.Timestamp(int(match[2]), int(match[1]), 1)
        except ValueError:
            return None
    return None


def eta_value(value, report_date):
    match = re.search(r"(\d{1,2})[./](\d{1,2})(?:[./](20\d{2}))?", str(value or ""))
    if not match:
        return None
    try:
        return pd.Timestamp(int(match[3] or report_date.year), int(match[2]), int(match[1]))
    except ValueError:
        return None


def xlsx_members(data, filename):
    if len(data) > MAX_BYTES:
        raise ValueError("Файл больше 100 МБ")
    if filename.lower().endswith(".xlsx"):
        yield filename, data
    elif filename.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            if len(members) > 100 or sum(m.file_size for m in members) > MAX_BYTES:
                raise ValueError("Архив превышает лимит 100 файлов / 100 МБ")
            for member in members:
                path = PurePosixPath(member.filename.replace("\\", "/"))
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("Недопустимый путь в архиве")
                if path.suffix.lower() == ".xlsx" and not path.name.startswith("~$"):
                    yield path.name, archive.read(member)
    else:
        raise ValueError("Ожидается ZIP или XLSX партнёра")


def read_partner(data, filename, supplier, report_date, confirmed_scope=None, iek_moq_meaning="unknown", inbound_base_units=False):
    if supplier not in ["IEK", "Systeme"]:
        raise ValueError("Выберите IEK или Systeme")
    report_date = pd.Timestamp(report_date)
    scope = confirmed_scope.strip() if confirmed_scope else "UNSPECIFIED"
    if not scope:
        raise ValueError("Пустая область склада")
    tables = defaultdict(list)
    products, monthly_records = {}, {}
    notes = ["Адаптеры проверены на синтетических макетах схем. Требуется сверка на оригинальных архивах.",
             "В исходных схемах нет customer_id, stockout-интервалов и сроков новых заказов. Эти поля не восстановлены автоматически."]
    if confirmed_scope:
        notes.append(f"Ручное допущение: отчёты и все склады накладных сведены в общую область «{scope}».")
    skipped = defaultdict(int)
    count = 0

    def product(sku, provenance, **fields):
        if sku not in products:
            products[sku] = dict(supplier_id=supplier, sku_1c=sku, name=f"Код {sku} (название не предоставлено)", **provenance)
        for key, value in fields.items():
            if value is not None and pd.notna(value):
                existing = products[sku].get(key)
                if key == "unit" and existing and existing != value:
                    notes.append(f"{sku}: разные единицы ({existing}, {value}); требуется конверсия")
                    products[sku]["unit"] = None
                    products[sku]["unit_conflict"] = "yes"
                elif key != "unit" or not products[sku].get("unit_conflict"):
                    products[sku][key] = value

    def sku_text(value):
        code = text(value)
        if not code or code.lower().startswith(("итого", "всего", "номенклат", "код")):
            return None
        if isinstance(value, (int, float)):
            notes.append("Часть кодов хранится числами в Excel: утраченные исходником ведущие нули автоматически не восстанавливаются.")
        return code

    def check_code(headers, index, label):
        value = str(headers[index] or "").lower() if len(headers) > index else ""
        if "код" not in value:
            raise ValueError(f"{label}: ожидаемый заголовок кода отсутствует; версия схемы изменилась")

    for file, payload in xlsx_members(data, filename):
        count += 1
        with zipfile.ZipFile(io.BytesIO(payload)) as package:
            if sum(m.file_size for m in package.infolist()) > MAX_BYTES:
                raise ValueError(f"{file}: распакованный XLSX больше 100 МБ")
        book = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
        lower = file.lower()
        try:
            if "динамик" in lower:
                sheet = book["Лист_1"] if "Лист_1" in book.sheetnames else book.worksheets[0]
                rows = sheet.iter_rows(values_only=True)
                headers = next(rows)
                mapping = {str(v or "").strip().lower(): i for i, v in enumerate(headers)}
                if not {"дата", "код", "документ", "количество"}.issubset(mapping):
                    raise ValueError(f"{file}: заголовки динамики не соответствуют аудиту")
                for rn, values in enumerate(rows, 2):
                    sku = sku_text(values[mapping["код"]])
                    raw_date = values[mapping["дата"]]
                    day = pd.to_datetime(raw_date, errors="coerce", dayfirst=True) if raw_date else pd.NaT
                    if not sku or pd.isna(day):
                        skipped[file] += 1
                        continue
                    prov = dict(source_file=file, source_sheet=sheet.title, source_row=str(rn), data_mode="partner")
                    unit = text(values[mapping.get("ед.", 5)])
                    product(sku, prov, name=text(values[4]), unit=unit)
                    dtype = str(values[mapping["документ"]] or "").lower()
                    kind = "sale" if dtype.startswith("расходная накладная") else "receipt" if dtype.startswith("приходная накладная") else "customer_order" if dtype.startswith("заказ покупателя") else "return" if dtype.startswith("возврат") else "unknown"
                    tables["sales"].append(dict(supplier_id=supplier, sku_1c=sku, warehouse_scope=scope if confirmed_scope else text(values[mapping.get("склад", 6)]) or "UNSPECIFIED", date=day,
                        document_id=text(values[mapping.get("номер", 1)]), customer_id=None, quantity_signed=numeric(values[mapping["количество"]]), unit=unit, document_type=kind, **prov))
            elif "tdsheet" in [s.lower() for s in book.sheetnames]:
                sheet = next(s for s in book if s.title.lower() == "tdsheet")
                headers = next(sheet.iter_rows(min_row=2, max_row=2, values_only=True))
                check_code(headers, 2, file)
                for col, token in [(4, "категор"), (49, "остат"), (50, "резерв"), (51, "остат"), (54, "пути")]:
                    if len(headers) <= col or token not in str(headers[col] or "").lower():
                        raise ValueError(f"{file}: заголовок колонки {col + 1} не соответствует V2; нужен разбор новой версии")
                months = {i: month_value(headers[i]) for i in range(6, min(41, len(headers)))}
                months = {i: m for i, m in months.items() if m is not None}
                if not months:
                    raise ValueError(f"{file}: не распознаны месяцы V2")
                for rn, values in enumerate(sheet.iter_rows(min_row=3, values_only=True), 3):
                    sku = sku_text(values[2])
                    if not sku:
                        skipped[file] += 1
                        continue
                    prov = dict(source_file=file, source_sheet=sheet.title, source_row=str(rn), data_mode="partner")
                    product(sku, prov, supplier_sku=text(values[1]), name=text(values[3]), category_id=text(values[4]))
                    for col, month in months.items():
                        quantity = numeric(values[col])
                        if quantity is not None and month <= report_date:
                            key = (sku, month)
                            monthly_records.setdefault(key, dict(supplier_id=supplier, sku_1c=sku, warehouse_scope=scope, month=month, qty_net=quantity,
                                is_complete=month + pd.offsets.MonthEnd(0) <= report_date, coverage_start=month, coverage_end=min(month + pd.offsets.MonthEnd(0), report_date), **prov))
                    tables["stock_snapshots"].append(dict(supplier_id=supplier, sku_1c=sku, warehouse_scope=scope, as_of=report_date,
                        on_hand=numeric(values[49]), reserved=numeric(values[50]), available=numeric(values[51]), snapshot_kind="current", **prov))
                    qty = numeric(values[54])
                    if qty is not None:
                        tables["inbound"].append(dict(supplier_id=supplier, sku_1c=sku, warehouse_scope=scope, order_id=f"{file}:BC", qty_base_unit=qty if inbound_base_units else None,
                            qty_source_unit=qty, eta=eta_value(headers[54], report_date), eta_kind="year_from_report", status="confirmed" if inbound_base_units else "pending", **prov))
                notes.append(f"{file}: AP/AQ (13 колонок под подписью 12 месяцев), AR/AS и подсуммы складов не используются. ETA без года получает год даты отчёта.")
            elif "ежемесяч" in lower:
                stock_report = "остат" in lower
                sheet = book["Лист_1"] if "Лист_1" in book.sheetnames else book.worksheets[0]
                headers = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))
                code_col = 2 if stock_report else 1
                check_code(headers, code_col, file)
                first_month = 3 if supplier == "IEK" and stock_report else 2 if supplier == "IEK" else 4
                months = {i: month_value(headers[i]) for i in range(first_month, len(headers))}
                months = {i: m for i, m in months.items() if m is not None}
                if not months:
                    raise ValueError(f"{file}: не распознаны месяцы; итоги не подменяют историю")
                for rn, values in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
                    sku = sku_text(values[code_col])
                    if not sku:
                        skipped[file] += 1
                        continue
                    prov = dict(source_file=file, source_sheet=sheet.title, source_row=str(rn), data_mode="partner")
                    product(sku, prov, name=text(values[0]), unit=text(values[3]) if stock_report and supplier == "Systeme" else None,
                        supplier_sku=text(values[2]) if not stock_report and supplier == "Systeme" else None,
                        order_multiple=numeric(values[3]) if not stock_report and supplier == "Systeme" else None)
                    for col, month in months.items():
                        qty = numeric(values[col])
                        if qty is None or month > report_date:
                            continue  # Missing cells remain absent observations, not zero.
                        if stock_report:
                            tables["stock_snapshots"].append(dict(supplier_id=supplier, sku_1c=sku, warehouse_scope=scope, as_of=month, on_hand=qty,
                                snapshot_kind="month_start" if supplier == "IEK" else "historical_unknown", **prov))
                        else:
                            monthly_records[(sku, month)] = dict(supplier_id=supplier, sku_1c=sku, warehouse_scope=scope, month=month, qty_net=qty,
                                is_complete=month + pd.offsets.MonthEnd(0) <= report_date, coverage_start=month, coverage_end=min(month + pd.offsets.MonthEnd(0), report_date), **prov)
                if stock_report:
                    notes.append(f"{file}: исторические остатки сохранены, но не используются как текущие.")
            elif "moq" in lower:
                sheet = book.worksheets[0]
                headers = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))
                check_code(headers, 1 if supplier == "IEK" else 2, file)
                for rn, values in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
                    code_col = 1 if supplier == "IEK" else 2
                    sku = sku_text(values[code_col])
                    if not sku:
                        continue
                    prov = dict(source_file=file, source_sheet=sheet.title, source_row=str(rn), data_mode="partner")
                    quantity = numeric(values[4])
                    fields = dict(supplier_sku=text(values[code_col + 1]), quantity_rule_source=f"{file}:{rn}")
                    if supplier == "Systeme" or iek_moq_meaning == "multiple":
                        fields["order_multiple"] = quantity
                    elif iek_moq_meaning == "minimum":
                        fields["min_order_qty"] = quantity
                    else:
                        fields["unconfirmed_moq"] = quantity
                    product(sku, prov, **fields)
                if supplier == "IEK" and iek_moq_meaning == "unknown":
                    notes.append("IEK «Мин. разр. к отгр.» сохранено как unconfirmed_moq: подтвердите minimum или multiple.")
            elif "путь" in lower and supplier == "IEK":
                sheet = book["Лист4"] if "Лист4" in book.sheetnames else book.worksheets[0]
                headers = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True))
                check_code(headers, 0, file)
                for rn, values in enumerate(sheet.iter_rows(min_row=2, values_only=True), 2):
                    sku = sku_text(values[0])
                    if not sku:
                        continue
                    prov = dict(source_file=file, source_sheet=sheet.title, source_row=str(rn), data_mode="partner")
                    product(sku, prov, supplier_sku=text(values[1]), name=text(values[2]))
                    for col in range(3, min(9, len(headers))):
                        qty = numeric(values[col])
                        if qty is None:
                            continue
                        tables["inbound"].append(dict(supplier_id=supplier, sku_1c=sku, warehouse_scope=scope,
                            order_id=f"{file}:{col + 1}", qty_base_unit=qty if inbound_base_units else None, qty_source_unit=qty,
                            eta=eta_value(headers[col], report_date), eta_kind="deadline" if "до" in str(headers[col]).lower() else "expected",
                            eta_header=text(headers[col]), status="confirmed" if inbound_base_units else "pending", **prov))
            elif "сезон" in lower:
                sheet = book["Сезонность"] if supplier == "IEK" and "Сезонность" in book.sheetnames else book["Лист1"] if "Лист1" in book.sheetnames else book.worksheets[0]
                start, column = (28, 6) if supplier == "IEK" else (11, 12)
                factors = []
                # One pass in read-only mode, never repeated random cell reads.
                for rn, values in enumerate(sheet.iter_rows(min_row=start, max_row=start + 11, values_only=True), start):
                    month_label = str(values[1] or "").lower()
                    month = next((n for stem, n in MONTHS.items() if stem in month_label), None)
                    if month is None and numeric(values[1]) in range(1, 13):
                        month = int(numeric(values[1]))
                    factor = numeric(values[column - 1])
                    if month and factor is not None:
                        factors.append(dict(supplier_id=supplier, month_of_year=month, factor=factor, known_as_of=report_date,
                            source=f"{file}/{sheet.title}", source_file=file, source_sheet=sheet.title, source_row=str(rn), data_mode="partner"))
                if len(factors) == 12 and all(r["factor"] > 0 for r in factors):
                    mean = sum(r["factor"] for r in factors) / 12
                    for record in factors:
                        record["raw_factor"] = record["factor"]
                        record["factor"] /= mean
                    tables["seasonal_prior"].extend(factors)
                else:
                    notes.append(f"{file}: не получено 12 положительных коэффициентов; возможно, формулы не имеют сохранённых значений. Prior не применён.")
            else:
                notes.append(f"{file}: формат не распознан, файл не использован.")
        finally:
            book.close()
    if count == 0:
        raise ValueError("В архиве нет XLSX")
    if not inbound_base_units:
        notes.append("Единицы пути не подтверждены. Партии pending не уменьшают заказ; заполните qty_base_unit и смените status на confirmed после проверки конверсии.")
    for file, number in skipped.items():
        notes.append(f"{file}: пропущено {number} служебных строк / строк без даты или кода.")
    notes.append(f"Обнаружено XLSX: {count}. Товаров: {len(products)}. Знаки количеств сохранены; поступления и заказы покупателей не считаются продажами.")
    tables["products"] = list(products.values())
    tables["monthly_sales"] = list(monthly_records.values())
    return normalize(Bundle({name: pd.DataFrame(records) for name, records in tables.items()}, list(dict.fromkeys(notes)), "partner"))
