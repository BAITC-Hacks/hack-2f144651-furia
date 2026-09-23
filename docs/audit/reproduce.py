"""Read-only synthetic reproductions for AUD-01 on the recorded base SHA.

These are evidence probes, not assertions that defective behavior is desirable.
After a fix, compare outcomes with the acceptance criteria in the audit report.
"""
import io
import json
from pathlib import Path
import runpy
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
import pandas as pd
from ekt.demo import DEMO_DATE, demo_bundle
from ekt.engine import Calculation, calculate
from ekt.export import xlsx_bytes
from ekt.ingest import read_canonical
from ekt.review import approve, export_frame, initial_edits
from ekt.schema import SCHEMAS, normalize, validate

make = runpy.run_path(str(ROOT / "tests" / "conftest.py"))["make_bundle"].__wrapped__()


def emit(case, **values):
    print(json.dumps(dict(case=case, **values), ensure_ascii=True), flush=True)


def fingerprint_collision():
    bundle = make()
    old = calculate(bundle, "2026-08-31")
    edits = initial_edits(old.rows)
    edits["adjusted_qty"] = float("nan")
    approval = approve(old, edits)
    bundle["sales"]["quantity_signed"] = 10.00000000004
    new = calculate(bundle, "2026-08-31")
    emit("fingerprint_precision", old_qty=old.rows.recommended_qty.tolist(),
         new_qty=new.rows.recommended_qty.tolist(), same_hash=old.fingerprint == new.fingerprint,
         status=export_frame(new, edits, approval).approval_status.tolist())


def large_prior():
    bundle = make()
    bundle.tables["seasonal_prior"] = pd.DataFrame(
        [["S", "A", month, 1e308, "2026-08-31", "synthetic"] for month in range(1, 13)],
        columns=SCHEMAS["seasonal_prior"])
    result = calculate(bundle, "2026-08-31")
    emit("prior_overflow", validation=validate(normalize(bundle)),
         rows=result.rows[["expected_demand_horizon", "recommended_qty"]].to_dict("records"))


def key_collision():
    first, second = make(), make(rate=20)
    for bundle, sku, scope in [(first, "X|Y", "Z"), (second, "X", "Y|Z")]:
        for frame in bundle.tables.values():
            if "sku_1c" in frame:
                frame["sku_1c"] = sku
            if "warehouse_scope" in frame:
                frame["warehouse_scope"] = scope
    for name in ["products", "sales", "stock_snapshots"]:
        first.tables[name] = pd.concat([first[name], second[name]], ignore_index=True)
    result = calculate(first, "2026-08-31")
    emit("row_id_collision", ids=result.rows.row_id.tolist(), details=len(result.details))


def override_tolerance():
    calculation = Calculation(pd.DataFrame({"row_id": ["a"], "recommended_qty": [1000000.]}), {}, "x", {})
    edits = initial_edits(calculation.rows)
    edits.loc[0, "adjusted_qty"] = 1000009.
    result = export_frame(calculation, edits, approve(calculation, edits))
    emit("override_tolerance", rows=result[["final_qty", "manager_override", "approval_status"]].to_dict("records"))


def duplicate_amplification():
    bundle = make("2026-08-01", "2026-08-03")
    bundle.tables["products"] = pd.concat([bundle["products"]] * 3, ignore_index=True)
    original, sizes = pd.DataFrame.merge, []

    def measured(left, right, *args, **kwargs):
        result = original(left, right, *args, **kwargs)
        sizes.append([len(left), len(right), len(result)])
        return result

    with patch.object(pd.DataFrame, "merge", measured):
        errors = validate(bundle)
    emit("validation_amplification", merge_sizes=sizes, validation_errors=len(errors))


def tiny_multiple():
    bundle = make()
    bundle["policies"]["order_multiple"] = 1e-308
    issues = validate(normalize(bundle))
    try:
        calculate(bundle, "2026-08-31")
    except Exception as exc:
        emit("multiple_overflow", validation=issues, error_type=type(exc).__name__)


def excel_codes():
    frame = pd.DataFrame({"supplier_id": ["S"] * 4,
                          "sku_1c": ["NA", "NULL", "N/A", "000001"], "name": ["Test"] * 4})
    buffer = io.BytesIO()
    frame.to_excel(buffer, sheet_name="products", index=False)
    workbook = read_canonical(buffer.getvalue(), "input.xlsx")
    csv = read_canonical(frame.to_csv(index=False).encode(), "products.csv")
    emit("xlsx_identifiers", xlsx=workbook["products"].sku_1c.fillna("<MISSING>").tolist(),
         csv=csv["products"].sku_1c.tolist())


def export_and_ui():
    from streamlit.testing.v1 import AppTest
    bundle = demo_bundle()
    bundle["products"].loc[0, "name"] = "Synthetic" + chr(11) + "item"
    calculation = calculate(bundle, DEMO_DATE)
    edits = initial_edits(calculation.rows)
    try:
        xlsx_bytes(export_frame(calculation, edits))
    except Exception as exc:
        emit("xlsx_control_character", validation=validate(bundle), error_type=type(exc).__name__)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    app.session_state.bundle = bundle
    app.session_state.version = 1
    app.session_state.calculation = calculation
    app.session_state.calc_version = 1
    app.run()
    emit("ui_eager_export_error", exceptions=[type(error).__name__ for error in app.exception],
         table_editor_reached="review_editor_key" in app.session_state)


def ambiguous_warehouses():
    from streamlit.testing.v1 import AppTest
    bundle = make(end="2026-09-22")
    for name in ("sales", "stock_snapshots"):
        other = bundle[name].copy()
        other["warehouse_scope"] = "W2"
        bundle.tables[name] = pd.concat([bundle[name], other], ignore_index=True)
    calculation = calculate(bundle, DEMO_DATE)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)
    app.session_state.bundle = bundle
    app.session_state.version = 1
    app.session_state.calculation = calculation
    app.session_state.calc_version = 1
    app.run()
    assert not app.exception
    grid = next(table.value for table in app.dataframe if "selected" in table.value)
    launcher = next(widget for widget in app.selectbox if widget.label == "Товар")
    emit("warehouse_identity_ui", scopes=calculation.rows.warehouse_scope.tolist(),
         warehouse_column="warehouse_scope" in grid, detail_labels=launcher.options)


if __name__ == "__main__":
    for probe in (fingerprint_collision, large_prior, key_collision, override_tolerance,
                  duplicate_amplification, tiny_multiple, excel_codes, export_and_ui, ambiguous_warehouses):
        probe()
