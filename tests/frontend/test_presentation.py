"""Presentation-only derivations never fill missing facts or alter engine rows."""
import pandas as pd
import pytest

from ekt.demo import DEMO_DATE, demo_bundle
from ekt.engine import calculate
from ekt.review import initial_edits
from ekt_ui.presentation import deliveries, filter_orders, number, order_grid, urgency_label


@pytest.mark.parametrize("qty,risk,urgency,expected", [
    (10, "2026-09-28", "Риск дефицита", "Критично"),
    (10, "2026-09-29", "Риск дефицита", "Пополнение"),
    (0, "", "Запаса достаточно", "Норма"),
    (None, "", "Нужны данные", "Нужны данные"),
])
def test_urgency_uses_engine_dates_and_unknowns(qty, risk, urgency, expected):
    row = pd.Series({"recommended_qty": qty, "risk_date": risk, "urgency": urgency})
    assert urgency_label(row, DEMO_DATE) == expected


@pytest.mark.parametrize("value,expected", [(0, "0"), (100, "100"), (1.25, "1.2"), (None, "Нет данных"), (float("nan"), "Нет данных")])
def test_number_distinguishes_zero_and_unknown(value, expected):
    assert number(value) == expected


def test_delivery_queue_preserves_missing_eta_quantities_and_units():
    bundle = demo_bundle()
    bundle["inbound"].loc[0, "eta"] = pd.NaT
    bundle["inbound"].loc[1, "eta"] = DEMO_DATE
    bundle["inbound"].loc[2, "status"] = "pending"
    bundle["inbound"].loc[2, "qty_base_unit"] = float("nan")
    bundle["inbound"].loc[3, "status"] = "cancelled"
    before = bundle["inbound"].copy()
    frame = deliveries(bundle, DEMO_DATE).set_index("order_id")
    assert frame.loc["IN-0", "delivery_state"] == "Нет ETA"
    assert frame.loc["LATE-0", "delivery_state"] == "Просрочена"
    assert frame.loc["IN-1", "delivery_state"] == "Не подтверждена"
    assert pd.isna(frame.loc["IN-1", "qty_base_unit"])
    assert frame.loc["IN-1", "unit"] == "м"
    assert frame.loc["IN-0", "unit"] == "шт"
    assert frame.loc["LATE-1", "delivery_state"] == "Отменена"
    pd.testing.assert_frame_equal(before, bundle["inbound"])


def test_ambiguous_product_mapping_does_not_duplicate_deliveries():
    bundle = demo_bundle()
    bundle.tables["products"] = pd.concat([bundle["products"], bundle["products"].iloc[[0]]], ignore_index=True)
    frame = deliveries(bundle, DEMO_DATE)
    assert len(frame) == len(bundle["inbound"])
    assert frame.loc[frame.order_id.eq("IN-0"), "unit"].isna().all()


def test_grid_is_read_only_and_sparklines_use_existing_raw_months():
    calculation = calculate(demo_bundle(), DEMO_DATE)
    before = calculation.rows.copy(deep=True)
    edits = initial_edits(calculation.rows)
    edits.loc[0, "adjusted_qty"] = 0
    grid = order_grid(calculation, edits)
    row_id = grid.row_id.iloc[0]
    assert grid.history.iloc[0] == calculation.details[row_id]["demand"].monthly.raw.tail(6).tolist()
    assert grid.manual_edit.iloc[0] == "Ручная правка"
    pd.testing.assert_frame_equal(before, calculation.rows)
    found = filter_orders(grid, ["IEK"], ["DEMO"], ["A", "B"], search="demo-cb16")
    assert found.row_id.tolist() == [row_id]
    assert filter_orders(grid, ["IEK"], ["DEMO"], ["A", "B"], search="[").empty
