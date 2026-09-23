"""Detector messages use scoped Logic results and preserve their limitations."""
from copy import deepcopy

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from ekt.demo import canonical_zip
from ekt.engine import calculate
from ekt.schema import SCHEMAS, normalize


def choose(app, kind, label):
    return next(widget for widget in getattr(app, kind) if widget.label == label)


def open_item(app, uploads, bundle, as_of, enabled=True):
    uploads["canonical"] = [("detector.zip", canonical_zip(bundle))]
    choose(app, "radio", "Источник данных").set_value("Мои данные").run()
    choose(app, "button", "Загрузить файлы").click().run()
    choose(app, "date_input", "Дата расчёта").set_value(pd.Timestamp(as_of).date()).run()
    choose(app, "toggle", "Исключать разовые заказы").set_value(enabled).run()
    choose(app, "button", "Рассчитать предложения").click().run()
    assert not app.exception
    choose(app, "button", "Почему столько?").click().run()
    assert not app.exception
    return app


@pytest.mark.parametrize("count,enabled,expected", [
    (11, True, "Недостаточно истории: 11 из 12 событий"),
    (11, False, "Аномалии не проверялись: детектор выключен"),
    (12, False, "Аномалии не проверялись: детектор выключен"),
    (12, True, "Эвристика применима и выполнена: найдено событий — 0; применено исключений — 0"),
])
def test_detector_states_in_real_item_dialog(app, uploads, make_bundle, count, enabled, expected):
    end = pd.Timestamp("2026-01-01") + pd.Timedelta(days=count - 1)
    bundle = make_bundle(start="2026-01-01", end=end)
    open_item(app, uploads, bundle, end, enabled)
    messages = [element.value for kind in ("info", "warning", "success") for element in getattr(app, kind)]
    assert any(expected in value for value in messages)
    if not enabled:
        assert not any("Недостаточно истории:" in value for value in messages)
        assert any("отключён: аномалии не проверены" in value.value for value in app.warning)
    elif count == 12:
        assert any("Пустой список не доказывает отсутствие аномалий" in value.value for value in app.caption)
    else:
        assert any("11 < 12" in value.value for value in app.warning)


def render_probe(bundle, calculation, row_id):
    import streamlit as st
    from ekt_ui.details import render_detector
    row = calculation.rows.loc[calculation.rows.row_id.eq(row_id)].iloc[0]
    render_detector(calculation, bundle, row, calculation.details.get(row_id))


def test_detector_scopes_all_keys_and_uses_cutoff_without_mutation(make_bundle):
    bundle = make_bundle(start="2026-01-01", end="2026-01-11")
    sales = bundle["sales"]
    # Every distracting group alone could make the unscoped detector eligible.
    others = [sales.assign(**{field: "OTHER"}) for field in ("supplier_id", "sku_1c", "warehouse_scope")]
    future = sales.iloc[[0]].assign(date=pd.Timestamp("2026-01-12"), document_id="future")
    split = sales.iloc[[0]].assign(document_id="split-invoice")
    returned = sales.iloc[[0]].assign(document_type="return", customer_id="return-only")
    bundle.tables["sales"] = pd.concat([sales, *others, future, split, returned], ignore_index=True)
    products = bundle["products"]
    bundle.tables["products"] = pd.concat([
        products, products.assign(supplier_id="OTHER"), products.assign(sku_1c="OTHER"),
    ], ignore_index=True)
    bundle = normalize(bundle)
    calculation = calculate(bundle, "2026-01-11")
    row_id = calculation.rows.loc[calculation.rows.warehouse_scope.eq("W"), "row_id"].iloc[0]
    before = bundle["sales"].copy(deep=True)
    app = AppTest.from_function(render_probe, args=(bundle, calculation, row_id)).run()
    assert not app.exception
    assert any("11 из 12 событий" in value.value for value in app.warning)
    assert not app.success
    pd.testing.assert_frame_equal(before, bundle["sales"])


def test_monthly_only_is_zero_events_not_proven_normal(app, uploads, make_bundle):
    bundle = make_bundle(start="2026-01-01", end="2026-01-31")
    bundle.tables["sales"] = bundle["sales"].iloc[:0]
    bundle.tables["monthly_sales"] = pd.DataFrame([
        ["S", "000001_", "W", "2026-01-01", 310, True, "2026-01-01", "2026-01-31"],
    ], columns=SCHEMAS["monthly_sales"])
    open_item(app, uploads, normalize(bundle), "2026-01-31")
    assert any("0 из 12 событий" in value.value for value in app.warning)
    assert not any("Эвристика применима и выполнена" in value.value for value in app.success)
    assert any("customer_id отсутствует" in value.value for value in app.warning)


def test_found_events_and_applied_exclusions_are_separate(app, uploads, make_bundle):
    bundle = make_bundle(start="2026-01-01", end="2026-01-31")
    extras = bundle["sales"].iloc[[4, 19]].copy()
    extras["quantity_signed"] = 1000
    extras["customer_id"] = ["oneoff-a", "oneoff-b"]
    extras["document_id"] = ["oneoff-a", "oneoff-b"]
    bundle.tables["sales"] = pd.concat([bundle["sales"], extras], ignore_index=True)
    bundle.tables["monthly_sales"] = pd.DataFrame([
        ["S", "000001_", "W", "2026-01-01", 200, False, "2026-01-01", "2026-01-10"],
    ], columns=SCHEMAS["monthly_sales"])
    open_item(app, uploads, normalize(bundle), "2026-01-31")
    assert any("найдено событий — 2; применено исключений — 1" in value.value for value in app.success)
    events = next(frame.value for frame in app.dataframe if "applied" in frame.value.columns)
    assert events.applied.tolist() == [False, True]
    assert any("не сходится с накладными" in value.value for value in app.warning)
    calculation = app.session_state["calculation"]
    assert calculation.rows.iloc[0].excluded_oneoff_qty == 1000
    assert calculation.details[calculation.rows.row_id.iloc[0]]["demand"].daily.corrected.sum() == 410


def test_eligibility_without_demand_result_does_not_claim_execution(make_bundle):
    bundle = make_bundle(start="2026-01-01", end="2026-01-12")
    bundle["products"].loc[0, "unit"] = pd.NA
    calculation = calculate(bundle, "2026-01-12")
    assert not calculation.details
    app = AppTest.from_function(render_probe, args=(bundle, calculation, calculation.rows.row_id.iloc[0])).run()
    assert not app.exception
    assert any("Эвристика применима, но результат проверки недоступен" in value.value for value in app.info)
    assert not app.success


def test_missing_stock_does_not_hide_completed_demand_check(make_bundle):
    bundle = make_bundle(start="2026-01-01", end="2026-01-12")
    bundle.tables["stock_snapshots"] = bundle["stock_snapshots"].iloc[:0]
    calculation = calculate(bundle, "2026-01-12")
    assert pd.isna(calculation.rows.iloc[0].recommended_qty)
    before = deepcopy(calculation)
    app = AppTest.from_function(render_probe, args=(bundle, calculation, calculation.rows.row_id.iloc[0])).run()
    assert not app.exception
    assert any("Эвристика применима и выполнена" in value.value for value in app.success)
    pd.testing.assert_frame_equal(before.rows, calculation.rows)
