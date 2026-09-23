"""View preferences must never change a purchasing decision or widen saved filters."""
import pandas as pd

from ekt.demo import demo_bundle
from ekt_ui.state import load_bundle
from ekt_ui.workspace import apply_saved_view, reconcile_filters


def widget(app, kind, label):
    return next(item for item in getattr(app, kind) if item.label == label)


def test_welcome_loads_real_synthetic_bundle(app):
    widget(app, "button", "Попробовать на демо").click().run()
    assert not app.exception
    assert app.session_state["bundle"].mode == "synthetic"
    assert "calculation" not in app.session_state
    widget(app, "button", "Рассчитать предложения").click().run()
    assert not app.exception
    assert len(app.session_state["calculation"].rows) == 4


def test_saved_views_and_density_preserve_zero_approval_and_export(calculated_app, downloads):
    app = calculated_app
    key = app.session_state["review_editor_key"]
    app.session_state[key] = {"edited_rows": {0: {"adjusted_qty": 0.0, "reason": "Already purchased"}},
                              "added_rows": [], "deleted_rows": []}
    app.run()
    widget(app, "button", "Утвердить выбранные позиции").click().run()
    approval = app.session_state["approval"]
    edits = app.session_state["review_edits"].copy()
    exported = downloads["csv"]
    widget(app, "segmented_control", "Поставщики").set_value("IEK").run()
    widget(app, "text_input", "Поиск товара").set_value("000001_").run()
    widget(app, "text_input", "Название представления").set_value("IEK search").run()
    widget(app, "button", "Сохранить / обновить").click().run()
    expected_ids = app.session_state["review_context"]
    assert len(expected_ids) == 1
    widget(app, "button", "Все позиции").click().run()
    assert len(app.session_state["review_context"]) == 4
    widget(app, "button", "Применить").click().run()
    assert app.session_state["review_context"] == expected_ids
    widget(app, "radio", "Плотность таблицы").set_value("Компактная").run()
    assert not app.exception
    assert app.session_state["approval"] == approval
    pd.testing.assert_frame_equal(app.session_state["review_edits"], edits)
    assert downloads["csv"] == exported
    widget(app, "button", "Мои правки").click().run()
    assert app.session_state["review_context"] == expected_ids
    widget(app, "button", "Удалить").click().run()
    assert not app.session_state["saved_views"]
    assert not app.exception


def test_saved_empty_selection_stays_empty(calculated_app):
    app = calculated_app
    widget(app, "multiselect", "Области склада").set_value([]).run()
    widget(app, "text_input", "Название представления").set_value("Empty").run()
    widget(app, "button", "Сохранить / обновить").click().run()
    widget(app, "button", "Все позиции").click().run()
    widget(app, "button", "Применить").click().run()
    assert not app.exception
    assert not app.session_state["review_context"]
    assert app.session_state["review_edits"].selected.all()


def test_unavailable_saved_scope_is_not_replaced_by_all(monkeypatch):
    import streamlit as st
    from streamlit.util import AttributeDictionary

    state = AttributeDictionary(saved_views={"old": {"supplier_group": "Old supplier",
        "order_categories": ["kept", "removed"], "order_scopes": ["old warehouse"],
        "order_search": "001", "order_risk": "Все"}})
    monkeypatch.setattr(st, "session_state", state)
    apply_saved_view("old")
    reconcile_filters(["IEK"], ["kept"], ["new warehouse"])
    assert state.order_scopes == []
    assert state.supplier_group == "Old supplier"
    assert state.order_categories == ["kept"]
    assert state.order_search == "001"
    assert state.saved_views["old"]["order_scopes"] == ["old warehouse"]


def test_preferences_survive_new_bundle_but_approval_does_not(monkeypatch):
    import streamlit as st
    from streamlit.util import AttributeDictionary

    state = AttributeDictionary(saved_views={"test": {"order_scopes": []}},
                                table_density="Компактная", approval=object(), calculation=object())
    monkeypatch.setattr(st, "session_state", state)
    load_bundle(demo_bundle())
    assert state.table_density == "Компактная"
    assert "test" in state.saved_views
    assert "approval" not in state and "calculation" not in state
