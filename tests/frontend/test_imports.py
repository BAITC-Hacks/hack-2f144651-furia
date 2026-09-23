"""Import messages reflect actual backend results, including partial inputs."""
from io import BytesIO

import pandas as pd
import pytest
from openpyxl import Workbook

from ekt.schema import PROVENANCE, fingerprint, validate


PRODUCTS = b"supplier_id,sku_1c,name,unit\nS,000001_,Test product,pcs\n"
INCOMPLETE_PRODUCTS = b"supplier_id,sku_1c,name\nS,000001_,\n"


def choose(app, kind, label):
    return next(widget for widget in getattr(app, kind) if widget.label == label)


def own_data(app):
    choose(app, "radio", "Источник данных").set_value("Мои данные").run()


def test_failed_first_import_explains_that_no_bundle_was_loaded(app, uploads):
    uploads["canonical"] = [("broken.zip", b"not a zip")]
    own_data(app)
    choose(app, "button", "Загрузить файлы").click().run()
    assert not app.exception
    assert "bundle" not in app.session_state
    assert any("broken.zip" in message.value for message in app.error)
    assert any("Набор не загружен" in message.value for message in app.info)
    app.run()
    assert any("Ошибка импорта" in message.value for message in app.error)
    choose(app, "radio", "Источник данных").set_value("Демонстрация").run()
    choose(app, "button", "Загрузить демо").click().run()
    assert "import_result" not in app.session_state
    assert not app.error


@pytest.mark.parametrize("append", [False, True])
def test_failed_multifile_import_keeps_previous_inputs_and_approval(calculated_app, uploads, append):
    app = calculated_app
    choose(app, "button", "Утвердить выбранные позиции").click().run()
    before = fingerprint(app.session_state["bundle"])
    calculation = app.session_state["calculation"]
    approval = app.session_state["approval"]
    version = app.session_state["version"]
    uploads["canonical"] = [("products.csv", PRODUCTS), ("broken.zip", b"not a zip")]
    own_data(app)
    choose(app, "checkbox", "Дополнить текущий набор (заменить только загружаемые таблицы)").set_value(append).run()
    choose(app, "button", "Загрузить файлы").click().run()
    assert not app.exception
    assert fingerprint(app.session_state["bundle"]) == before
    assert app.session_state["calculation"] is calculation
    assert app.session_state["approval"] == approval
    assert app.session_state["version"] == version
    assert any("Ошибка импорта" in message.value for message in app.error)
    assert any("набор сохранён без изменений" in message.value for message in app.info)
    app.run()
    assert fingerprint(app.session_state["bundle"]) == before
    assert app.session_state["approval"] == approval
    assert any("Ошибка импорта" in message.value for message in app.error)


@pytest.mark.parametrize("mode,label", [
    ("manual", "Ручные / тестовые входы"),
    ("partner", "Данные партнёра"),
    ("synthetic", "Синтетические данные"),
])
def test_successful_partial_import_shows_actual_rows_and_origin(app, uploads, mode, label):
    uploads["canonical"] = [("products.csv", PRODUCTS)]
    own_data(app)
    choose(app, "selectbox", "Происхождение").set_value(label).run()
    choose(app, "button", "Загрузить файлы").click().run()
    assert not app.exception
    bundle = app.session_state["bundle"]
    assert bundle.mode == mode
    assert bundle["products"].data_mode.eq(mode).all()
    assert bundle["products"].sku_1c.tolist() == ["000001_"]
    summary = app.dataframe[0].value.set_index("Таблица")
    assert summary.loc["products", "Строк"] == 1
    assert summary.loc["sales", "Строк"] == 0
    assert summary.loc["products", "Происхождение строк"] == mode
    assert any(f"Происхождение набора: {mode}" == message.value for message in app.caption)
    assert not validate(bundle)
    assert any("не подтверждают полноту" in message.value for message in app.caption)
    assert any("validate: ошибок структуры не обнаружено" in message.value for message in app.info)
    assert any("products.csv" in message.value for message in app.success)
    app.run()
    assert any("products.csv" in message.value for message in app.success)


def test_import_with_validation_errors_is_available_for_editing(calculated_app, uploads):
    app = calculated_app
    choose(app, "button", "Утвердить выбранные позиции").click().run()
    version = app.session_state["version"]
    uploads["canonical"] = [("products.csv", INCOMPLETE_PRODUCTS)]
    own_data(app)
    choose(app, "button", "Загрузить файлы").click().run()
    assert not app.exception
    assert app.session_state["version"] == version + 1
    assert "calculation" not in app.session_state
    assert "approval" not in app.session_state
    assert "input_signature" not in app.session_state
    assert any("набор обновлён локально" in message.value for message in app.success)
    issues = validate(app.session_state["bundle"])
    assert issues
    for issue in issues:
        assert any(issue in message.value for message in app.error)
    assert choose(app, "button", "Сохранить таблицу")
    assert not any("СИНТЕТИЧЕСКИЕ" in message.value for message in app.caption)


def test_successful_append_keeps_other_tables_notes_and_row_origins(calculated_app, uploads):
    app = calculated_app
    choose(app, "button", "Утвердить выбранные позиции").click().run()
    before = app.session_state["bundle"].copy()
    products = before["products"].drop(columns=PROVENANCE)
    products.loc[0, "name"] = "Manually imported product"
    uploads["canonical"] = [("products.csv", products.to_csv(index=False).encode("utf-8"))]
    own_data(app)
    choose(app, "checkbox", "Дополнить текущий набор (заменить только загружаемые таблицы)").set_value(True).run()
    choose(app, "button", "Загрузить файлы").click().run()
    assert not app.exception
    after = app.session_state["bundle"]
    assert after.mode == "synthetic"
    assert after["products"].iloc[0]["name"] == "Manually imported product"
    assert after["products"].data_mode.eq("manual").all()
    for name in before.tables:
        if name != "products":
            pd.testing.assert_frame_equal(before[name], after[name])
    assert after.notes == before.notes
    assert all(note in [message.value for message in app.caption] for note in after.notes)
    assert "calculation" not in app.session_state
    assert "approval" not in app.session_state
    summary = app.dataframe[0].value.set_index("Таблица")
    assert summary.loc["products", "Происхождение строк"] == "manual"
    assert summary.loc["sales", "Происхождение строк"] == "synthetic"


@pytest.mark.parametrize("confirm_scope", [False, True])
def test_partner_import_failure_preserves_existing_bundle(calculated_app, uploads, confirm_scope):
    app = calculated_app
    choose(app, "button", "Утвердить выбранные позиции").click().run()
    before = fingerprint(app.session_state["bundle"])
    approval = app.session_state["approval"]
    uploads["partner"] = ("reports.zip", b"not a zip")
    own_data(app)
    choose(app, "selectbox", "Формат").set_value("Отчёты IEK / Systeme").run()
    choose(app, "checkbox", "Подтверждаю единую область всех отчётов и складов").set_value(confirm_scope).run()
    choose(app, "button", "Импортировать отчёты").click().run()
    assert not app.exception
    assert fingerprint(app.session_state["bundle"]) == before
    assert app.session_state["approval"] == approval
    assert any("reports.zip" in message.value for message in app.error)
    if confirm_scope:
        assert any("Введите название" in message.value for message in app.error)
    assert any("набор сохранён без изменений" in message.value for message in app.info)


def test_partner_import_displays_all_adapter_notes_without_claiming_coverage(app, uploads):
    book = Workbook()
    book.active.title = "Лист7"
    book.active.append(["N", "Код 1С", "Артикул", "Наименование", "Мин. разр. к отгр."])
    book.active.append([1, "000001_", "A000", "Synthetic fixture only", 10])
    data = BytesIO()
    book.save(data)
    uploads["partner"] = ("MOQ.xlsx", data.getvalue())
    own_data(app)
    choose(app, "selectbox", "Формат").set_value("Отчёты IEK / Systeme").run()
    choose(app, "button", "Импортировать отчёты").click().run()
    assert not app.exception
    bundle = app.session_state["bundle"]
    assert bundle.mode == "partner"
    assert bundle.notes
    captions = [message.value for message in app.caption]
    assert all(note in captions for note in bundle.notes)
    assert any("XLSX: 1" in note for note in bundle.notes)
    assert any("unconfirmed_moq" in note for note in bundle.notes)
    assert bundle["stock_snapshots"].empty
    assert bundle["sales"].empty
    assert bundle["products"].sku_1c.tolist() == ["000001_"]
    assert any("MOQ.xlsx" in message.value for message in app.success)
