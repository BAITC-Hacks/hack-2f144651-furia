"""Regression coverage for input edits, approval and unfiltered downloads."""
from datetime import timedelta
from io import BytesIO

import pandas as pd
import pytest
from openpyxl import load_workbook


def choose(app, kind, label):
    return next(widget for widget in getattr(app, kind) if widget.label == label)


def edit_rows(app, key, edits):
    # AppTest has no data_editor setter and does not resend its state on reruns.
    # Supply the browser edit payload before each interaction involving these edits.
    app.session_state[key] = {"edited_rows": edits, "added_rows": [], "deleted_rows": []}


@pytest.mark.parametrize("option", ["Дата расчёта", "Исключать разовые заказы", "Восстанавливать stockout"])
def test_calculation_option_change_invalidates_result_and_approval(calculated_app, option):
    app = calculated_app
    choose(app, "button", "Утвердить выбранные позиции").click().run()
    assert "approval" in app.session_state
    if option == "Дата расчёта":
        widget = choose(app, "date_input", option)
        widget.set_value(widget.value + timedelta(days=1)).run()
    else:
        choose(app, "toggle", option).set_value(False).run()
    assert not app.exception
    assert "calculation" not in app.session_state
    assert "approval" not in app.session_state
    assert "input_signature" not in app.session_state


def test_saving_inputs_invalidates_calculation_and_marks_only_edit_manual(calculated_app):
    app = calculated_app
    choose(app, "button", "Утвердить выбранные позиции").click().run()
    before = app.session_state["bundle"]["products"].copy()
    version = app.session_state["version"]
    edit_rows(app, f"data_{version}_products", {0: {"name": "Edited product"}})
    choose(app, "button", "Сохранить таблицу").click().run()
    assert not app.exception
    after = app.session_state["bundle"]["products"]
    assert after.iloc[0]["name"] == "Edited product"
    assert after.iloc[0]["data_mode"] == "manual"
    pd.testing.assert_frame_equal(before.iloc[1:], after.iloc[1:])
    assert app.session_state["bundle"].mode == "synthetic"
    assert "calculation" not in app.session_state
    assert "approval" not in app.session_state
    assert app.session_state["version"] == version + 1


def test_manual_zero_requires_reason_and_review_edit_invalidates_approval(calculated_app, downloads):
    app = calculated_app
    choose(app, "button", "Утвердить выбранные позиции").click().run()
    assert "approval" in app.session_state
    key = f"review_{app.session_state['calc_version']}"
    edit_rows(app, key, {0: {"adjusted_qty": 0.0}})
    app.run()
    assert not app.exception
    assert "approval" not in app.session_state
    exported = pd.read_csv(BytesIO(downloads["csv"]), sep=";")
    assert exported.iloc[0].final_qty == 0
    assert exported.approval_status.eq("draft").all()
    edit_rows(app, key, {0: {"adjusted_qty": 0.0}})
    choose(app, "button", "Утвердить выбранные позиции").click().run()
    assert "approval" not in app.session_state
    assert any("Укажите причину" in message.value for message in app.error)
    edit_rows(app, key, {0: {"adjusted_qty": 0.0, "reason": "Manual zero for review test"}})
    choose(app, "button", "Утвердить выбранные позиции").click().run()
    assert not app.exception
    assert "approval" in app.session_state
    exported = pd.read_csv(BytesIO(downloads["csv"]), sep=";")
    assert exported.iloc[0].final_qty == 0
    assert exported.iloc[0].manager_override
    assert exported.approval_status.eq("approved").all()
    book = load_workbook(BytesIO(downloads["xlsx"]), read_only=True)
    records = list(book.worksheets[0].values)
    assert records[1][records[0].index("final_qty")] == 0
    assert records[1][records[0].index("approval_status")] == "approved"
    book.close()


def test_deselecting_all_rows_revokes_approval_and_hides_downloads(calculated_app):
    app = calculated_app
    choose(app, "button", "Утвердить выбранные позиции").click().run()
    key = f"review_{app.session_state['calc_version']}"
    rows = app.session_state["calculation"].rows
    edit_rows(app, key, {i: {"selected": False} for i in range(len(rows))})
    app.run()
    assert not app.exception
    assert "approval" not in app.session_state
    labels = [button.label for button in app.get("download_button")]
    assert "Скачать CSV" not in labels
    assert "Скачать XLSX" not in labels


@pytest.mark.parametrize("filter_label", ["Поставщики для просмотра", "Области склада", "Категории"])
def test_empty_display_filter_does_not_change_approved_export(calculated_app, downloads, filter_label):
    app = calculated_app
    choose(app, "button", "Утвердить выбранные позиции").click().run()
    expected = downloads["csv"]
    approval = app.session_state["approval"]
    choose(app, "multiselect", filter_label).set_value([]).run()
    assert not app.exception
    assert app.session_state["approval"] == approval
    assert downloads["csv"] == expected
    visible = next(table.value for table in app.dataframe if "recommended_qty" in table.value and "row_id" not in table.value)
    assert visible.empty
    exported = pd.read_csv(BytesIO(downloads["csv"]), sep=";")
    assert len(exported) == 4
    assert exported.supplier_id.nunique() == 2
    assert exported.approval_status.eq("approved").all()
