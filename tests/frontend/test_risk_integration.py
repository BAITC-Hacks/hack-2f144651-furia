"""Logic risk states stay consistent across the purchasing UI and review edits."""
from io import BytesIO

import pandas as pd
import pytest

from ekt.demo import DEMO_DATE, demo_bundle
from ekt.engine import Calculation, calculate
from ekt.review import approve, export_frame, initial_edits
from ekt.schema import SCHEMAS
from ekt_ui.presentation import filter_orders, order_grid, urgency_label


@pytest.mark.parametrize("quantity,risk_date,urgency,expected", [
    (10, "2026-09-28", None, "Критично"),
    (10, "2026-09-29", None, "Пополнение"),
    (0, "2026-09-23", "Риск дефицита", "Критично"),
    (20, "", "Плановый заказ", "Пополнение"),
    (0, "", "Запаса достаточно", "Норма"),
    (20, "invalid", "Риск дефицита", "Риск не определён"),
    (0, "", None, "Риск не определён"),
    (None, "2026-09-23", "Риск дефицита", "Нужны данные"),
    (float("inf"), "", "Плановый заказ", "Нужны данные"),
    (-1, "", "Запаса достаточно", "Нужны данные"),
])
def test_labels_preserve_unknown_and_quantity_independent_risk(quantity, risk_date, urgency, expected):
    row = pd.Series({"recommended_qty": quantity, "risk_date": risk_date, "urgency": urgency})
    original = row.copy(deep=True)
    assert urgency_label(row, "2026-09-22") == expected
    pd.testing.assert_series_equal(row, original)


@pytest.mark.parametrize("available,inbound,eta,safety,quantity,priority,at_risk", [
    (30, 25, "2026-09-04", 2, 65, "Критично", True),
    (40, 25, "2026-09-04", 2, 55, "Пополнение", True),
    (0, 100, "2026-09-10", 0, 0, "Критично", True),
    (100, 0, "2026-09-10", 2, 20, "Пополнение", False),
    (200, 0, "2026-09-10", 2, 0, "Норма", False),
])
def test_calculated_grid_risk_and_manual_zero_do_not_change_numbers(
        make_bundle, available, inbound, eta, safety, quantity, priority, at_risk):
    bundle = make_bundle()
    bundle["policies"].loc[:, ["lead_time_days", "review_days", "safety_days"]] = [7, 3, safety]
    bundle["stock_snapshots"].loc[:, ["on_hand", "reserved", "available"]] = [available, 0, available]
    bundle.tables["inbound"] = pd.DataFrame([
        ["S", "000001_", "W", "arrival", inbound, eta, "confirmed", "confirmed"],
    ], columns=SCHEMAS["inbound"])
    calculation = calculate(bundle, "2026-08-31")
    original = calculation.rows.copy(deep=True)
    edits = initial_edits(calculation.rows)
    edits.loc[:, "selected"] = True
    edits.loc[:, "adjusted_qty"] = 0.0
    edits.loc[:, "reason"] = "Ручной ноль"
    grid = order_grid(calculation, edits)
    assert grid.priority.tolist() == [priority]
    assert grid.recommended_qty.tolist() == [quantity]
    assert grid.adjusted_qty.tolist() == [0]
    assert grid.expected_demand_horizon.tolist() == pytest.approx([100])
    selected = filter_orders(grid, ["S"], ["W"], ["A"], "Риск дефицита")
    assert (not selected.empty) is at_risk
    approved = export_frame(calculation, edits, approve(calculation, edits))
    assert approved.final_qty.tolist() == [0]
    assert approved.approval_status.tolist() == ["approved"]
    pd.testing.assert_frame_equal(calculation.rows, original)


def risk_calculation():
    """A synthetic Calculation exercises malformed metadata alongside real row fields."""
    calculation = calculate(demo_bundle(), DEMO_DATE)
    template = calculation.rows.iloc[0].copy()
    cases = [
        ("six", 10, "2026-09-28", None, ""),
        ("seven", 10, "2026-09-29", None, ""),
        ("zero_risk", 0, "2026-09-23", "Риск дефицита", ""),
        ("safety", 20, "", "Плановый заказ", ""),
        ("normal", 0, "", "Запаса достаточно", ""),
        ("unknown", 20, "invalid", "Риск дефицита", ""),
        ("unavailable", None, "2026-09-23", "Риск дефицита", ""),
        ("warning", 0, "", "Запаса достаточно", "Предупреждение движка"),
    ]
    rows = []
    for row_id, quantity, risk_date, urgency, warning in cases:
        row = template.to_dict()
        row.update({"row_id": row_id, "name": row_id, "recommended_qty": quantity,
                    "risk_date": risk_date, "urgency": urgency, "data_warnings": warning,
                    "as_of": "1999-01-01"})
        rows.append(row)
    return Calculation(pd.DataFrame(rows).reset_index(drop=True), {}, calculation.fingerprint, calculation.config)


def choose(app, kind, label):
    return next(widget for widget in getattr(app, kind) if widget.label == label)


def test_grid_passes_unedited_rows_and_config_date_to_logic(monkeypatch):
    from ekt_ui import presentation

    calculation = risk_calculation()
    edits = initial_edits(calculation.rows).iloc[::-1].copy()
    edits.loc[:, "adjusted_qty"] = 0.0
    received = []
    classify = presentation.classify_risk

    def capture(row, as_of):
        received.append((row.copy(deep=True), as_of))
        return classify(row, as_of)

    monkeypatch.setattr(presentation, "classify_risk", capture)
    grid = order_grid(calculation, edits)
    assert grid.row_id.tolist() == calculation.rows.row_id.tolist()
    assert {row.row_id for row, _ in received} == set(calculation.rows.row_id)
    for row, as_of in received:
        assert as_of == calculation.config["as_of"]
        pd.testing.assert_series_equal(row, calculation.rows.loc[calculation.rows.row_id.eq(row.row_id)].iloc[0])


def test_dashboard_risk_filters_kpis_and_global_export_use_calculation_status(app, monkeypatch, downloads):
    from ekt_ui import results

    calculation = risk_calculation()
    original = calculation.rows.copy(deep=True)
    monkeypatch.setattr(results, "calculate", lambda *args: calculation)
    choose(app, "button", "Загрузить демо").click().run()
    choose(app, "button", "Рассчитать предложения").click().run()
    assert not app.exception
    assert choose(app, "metric", "Риск дефицита").value == "3"
    assert choose(app, "metric", "Требует перепроверки").value == "3"
    choose(app, "button", "Выбрать видимые").click().run()
    assert not app.exception

    # UI edits, selection, filters, and export keep their existing row_id semantics.
    key = app.session_state["review_editor_key"]
    app.session_state[key] = {"edited_rows": {0: {"adjusted_qty": 0.0, "reason": "Ручной ноль"}},
                              "added_rows": [], "deleted_rows": []}
    app.run()
    assert not app.exception
    choose(app, "button", "Утвердить выбранные позиции").click().run()
    assert not app.exception
    exported_before = downloads["csv"]
    approval = app.session_state["approval"]

    for risk, expected in [
        ("Риск дефицита", ["six", "seven", "zero_risk"]),
        ("Критично", ["six", "zero_risk"]),
        ("Пополнение", ["seven", "safety"]),
        ("Норма", ["normal", "warning"]),
        ("Нужны данные", ["unavailable"]),
        ("Риск не определён", ["unknown"]),
    ]:
        choose(app, "selectbox", "Уровень риска").set_value(risk).run()
        assert not app.exception
        assert list(app.session_state["review_context"]) == expected
        assert choose(app, "metric", "Риск дефицита").value == "3"
        assert choose(app, "metric", "Требует перепроверки").value == "3"
        assert app.session_state["approval"] == approval
        assert downloads["csv"] == exported_before

    exported = pd.read_csv(BytesIO(downloads["csv"]), sep=";")
    assert exported.row_id.tolist() == ["six", "seven", "zero_risk", "safety", "normal", "unknown", "warning"]
    assert exported.approval_status.eq("approved").all()
    assert exported.set_index("row_id").loc["six", "final_qty"] == 0
    assert "risk_level" not in exported.columns
    choose(app, "button", "Почему столько?").click().run()
    assert not app.exception
    assert any(":orange-badge[Риск не определён]" == item.value for item in app.markdown)
    pd.testing.assert_frame_equal(calculation.rows, original)
