"""Synthetic regressions for layouts found while checking private originals."""
from datetime import datetime
import io

from openpyxl import Workbook
import pytest

from ekt.partner import read_partner


@pytest.mark.parametrize("supplier", ["IEK", "Systeme"])
@pytest.mark.parametrize("numbered", [False, True])
def test_monthly_stock_name_comes_from_its_header_not_ordinal(supplier, numbered):
    book = Workbook()
    sheet = book.active
    sheet.title = "Лист_1"
    if numbered:
        headers = ["№", "Номенклатура", "Номенклатура.Код"]
        row = [42, "Synthetic stock product", "000007_"]
    else:
        headers = ["Наименование", "Артикул", "Код"]
        row = ["Synthetic stock product", "TEST-ARTICLE", "000007_"]
    if supplier == "Systeme":
        headers.append("Ед.изм")
        row.append("шт")
    sheet.append(headers + [datetime(2026, 9, 1)])
    sheet.append(row + [17])
    payload = io.BytesIO()
    book.save(payload)
    book.close()

    bundle = read_partner(payload.getvalue(), "Ежемесячные остатки.xlsx", supplier, "2026-09-22")

    product = bundle["products"].iloc[0]
    stock = bundle["stock_snapshots"].iloc[0]
    assert product["name"] == "Synthetic stock product"
    assert product.sku_1c == stock.sku_1c == "000007_"
    assert stock.on_hand == 17
    assert product.source_row == stock.source_row == "2"
    assert stock.warehouse_scope == "UNSPECIFIED"
