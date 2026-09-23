"""Foreign-key validation must preserve supplier scope without expanding rows."""

import pandas as pd
import pytest

from ekt.schema import Bundle, normalize, validate


REFERENCE_ROWS = {
    "sales": {"date": "2026-06-01", "document_id": "D1", "customer_id": "C1",
              "quantity_signed": 1, "unit": "шт", "document_type": "sale"},
    "monthly_sales": {"month": "2026-06-01", "qty_net": 1, "is_complete": True,
                      "coverage_start": "2026-06-01", "coverage_end": "2026-06-30"},
    "stock_snapshots": {"as_of": "2026-06-01", "on_hand": 1, "reserved": 0,
                        "available": 1, "snapshot_kind": "current"},
    "inbound": {"order_id": "O1", "qty_base_unit": 1, "eta": "2026-06-02",
                "eta_kind": "exact", "status": "confirmed"},
    "stockouts": {"start_date": "2026-06-01", "end_date": "2026-06-02",
                  "evidence": "manual"},
}


def _bundle(table_name, keys):
    products = pd.DataFrame([
        {"supplier_id": "S", "sku_1c": "000001", "name": "First", "unit": "шт"},
        {"supplier_id": "T", "sku_1c": "000002", "name": "Second", "unit": "шт"},
    ])
    references = pd.DataFrame([
        {**REFERENCE_ROWS[table_name], "supplier_id": supplier_id,
         "sku_1c": sku_1c, "warehouse_scope": "W"}
        for supplier_id, sku_1c in keys
    ])
    return normalize(Bundle({"products": products, table_name: references}, mode="synthetic"))


def test_duplicate_products_do_not_expand_foreign_key_validation(monkeypatch):
    bundle = _bundle("sales", [("S", "000001")] * 3)
    bundle.tables["products"] = pd.concat([bundle["products"].iloc[[0]]] * 3, ignore_index=True)
    merge_sizes = []
    original_merge = pd.DataFrame.merge

    def observed_merge(left, *args, **kwargs):
        result = original_merge(left, *args, **kwargs)
        merge_sizes.append((len(left), len(result)))
        return result

    monkeypatch.setattr(pd.DataFrame, "merge", observed_merge)
    errors = validate(bundle)

    assert any(error.startswith("products: дубли ключа") for error in errors)
    assert not any("без соответствия в products" in error for error in errors)
    assert all(output_rows <= input_rows for input_rows, output_rows in merge_sizes), merge_sizes
    assert len(bundle["sales"]) == 3


@pytest.mark.parametrize("table_name", REFERENCE_ROWS)
@pytest.mark.parametrize("supplier_id, sku_1c, unknown", [
    ("S", "000001", False),
    ("T", "000002", False),
    ("S", "000002", True),  # Existing SKU belongs to another supplier.
    ("unknown-supplier", "000001", True),
    ("S", "unknown-sku", True),
])
def test_foreign_key_membership_requires_supplier_and_sku(table_name, supplier_id, sku_1c, unknown):
    bundle = _bundle(table_name, [(supplier_id, sku_1c)])

    errors = validate(bundle)

    expected = [f"{table_name}: есть коды без соответствия в products"] if unknown else []
    assert errors == expected
