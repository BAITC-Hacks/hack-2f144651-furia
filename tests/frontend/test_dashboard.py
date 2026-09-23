"""Purchasing grid workflows across suppliers, filters and the detail dialog."""
from io import BytesIO

import pandas as pd


def choose(app, kind, label):
    return next(widget for widget in getattr(app, kind) if widget.label == label)


def edit_order(app, index, **changes):
    key = app.session_state["review_editor_key"]
    app.session_state[key] = {"edited_rows": {index: changes}, "added_rows": [], "deleted_rows": []}
    app.run()
    assert not app.exception


def test_edits_survive_supplier_switch_for_identical_sku(calculated_app, downloads):
    app = calculated_app
    row_ids = app.session_state["calculation"].rows.row_id.tolist()
    edit_order(app, 0, adjusted_qty=0.0, reason="Do not reorder IEK")
    choose(app, "segmented_control", "Поставщики").set_value("Systeme").run()
    edit_order(app, 0, adjusted_qty=1.0, reason="One unit for Systeme")
    choose(app, "segmented_control", "Поставщики").set_value("IEK").run()
    edits = app.session_state["review_edits"].set_index("row_id")
    assert edits.loc[row_ids[0], "adjusted_qty"] == 0
    assert edits.loc[row_ids[2], "adjusted_qty"] == 1
    assert edits.loc[row_ids[0], "reason"] == "Do not reorder IEK"
    assert edits.loc[row_ids[2], "reason"] == "One unit for Systeme"
    assert any("Скрыто фильтрами: 2" in value.value for value in app.caption)
    choose(app, "button", "Утвердить выбранные позиции").click().run()
    assert not app.exception
    exported = pd.read_csv(BytesIO(downloads["csv"]), sep=";")
    assert len(exported) == 4
    assert exported.approval_status.eq("approved").all()
    assert exported.loc[exported.row_id.eq(row_ids[0]), "final_qty"].iloc[0] == 0
    assert exported.loc[exported.row_id.eq(row_ids[2]), "final_qty"].iloc[0] == 1


def test_batch_selection_affects_visible_rows_only(calculated_app, downloads):
    app = calculated_app
    choose(app, "button", "Утвердить выбранные позиции").click().run()
    choose(app, "segmented_control", "Поставщики").set_value("IEK").run()
    choose(app, "button", "Снять видимые").click().run()
    assert not app.exception
    assert "approval" not in app.session_state
    exported = pd.read_csv(BytesIO(downloads["csv"]), sep=";")
    assert exported.supplier_id.tolist() == ["Systeme", "Systeme"]
    choose(app, "button", "Выбрать видимые").click().run()
    assert app.session_state["review_edits"].selected.all()
    assert len(pd.read_csv(BytesIO(downloads["csv"]), sep=";")) == 4


def test_reset_restores_recommendations_and_cancels_approval(calculated_app):
    app = calculated_app
    edit_order(app, 0, adjusted_qty=0.0, reason="Manual test")
    choose(app, "button", "Утвердить выбранные позиции").click().run()
    choose(app, "button", "Сбросить изменения").click().run()
    assert not app.exception
    assert "approval" not in app.session_state
    edits = app.session_state["review_edits"]
    assert edits.reason.eq("").all()
    assert edits.selected.all()
    assert edits.adjusted_qty.tolist() == app.session_state["calculation"].rows.recommended_qty.tolist()


def test_reset_cancels_approval_even_without_quantity_changes(calculated_app):
    app = calculated_app
    choose(app, "button", "Утвердить выбранные позиции").click().run()
    assert "approval" in app.session_state
    choose(app, "button", "Сбросить изменения").click().run()
    assert not app.exception
    assert "approval" not in app.session_state


def test_search_and_manual_filter_preserve_edits_and_export(calculated_app, downloads):
    app = calculated_app
    edit_order(app, 0, adjusted_qty=0.0, reason="Manual test")
    choose(app, "selectbox", "Уровень риска").set_value("Ручные правки").run()
    assert len(app.session_state["review_context"]) == 1
    choose(app, "text_input", "Поиск товара").set_value("[").run()
    assert not app.exception
    assert len(app.session_state["review_context"]) == 0
    choose(app, "text_input", "Поиск товара").set_value("000001_").run()
    assert len(app.session_state["review_context"]) == 1
    assert app.session_state["review_edits"].iloc[0].adjusted_qty == 0
    assert len(pd.read_csv(BytesIO(downloads["csv"]), sep=";")) == 4


def test_details_show_actual_engine_components(calculated_app):
    app = calculated_app
    row = app.session_state["calculation"].rows.iloc[0]
    choose(app, "button", "Почему столько?").click().run()
    assert not app.exception
    assert any(value.value == row["name"] for value in app.subheader)
    assert any(row.explanation == value.value for value in app.markdown)
    assert choose(app, "metric", "Доступный остаток").value == "30"
    assert choose(app, "metric", "Путь в горизонте").value == "20"
    assert any("ABC/XYZ: не рассчитаны" in value.value for value in app.caption)
    assert len(app.get("vega_lite_chart")) >= 2


def test_partial_inputs_stay_unknown_in_dashboard(app, uploads):
    uploads["canonical"] = [("products.csv", b"supplier_id,sku_1c,name,unit\nS,000001_,Product,pcs\n")]
    choose(app, "radio", "Источник данных").set_value("Мои данные").run()
    choose(app, "button", "Загрузить файлы").click().run()
    choose(app, "button", "Рассчитать предложения").click().run()
    assert not app.exception
    rows = app.session_state["calculation"].rows
    assert rows.recommended_qty.isna().all()
    assert not app.session_state["review_edits"].selected.any()
    assert choose(app, "metric", "Общая сумма заказа").value == "Нет цен"
    choose(app, "button", "Выбрать видимые").click().run()
    assert not app.session_state["review_edits"].selected.any()
    assert choose(app, "button", "Утвердить выбранные позиции").disabled
    choose(app, "button", "Почему столько?").click().run()
    assert not app.exception
    assert any("Прогноз для позиции не построен" in value.value for value in app.info)


def test_recalculation_clears_old_manual_edits(calculated_app):
    app = calculated_app
    edit_order(app, 0, adjusted_qty=0.0, reason="Manual test")
    choose(app, "button", "Рассчитать предложения").click().run()
    assert not app.exception
    assert app.session_state["review_edits"].iloc[0].adjusted_qty > 0
    assert app.session_state["review_edits"].reason.eq("").all()
