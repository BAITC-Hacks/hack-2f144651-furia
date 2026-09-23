"""Local import controls and feedback; adapters own parsing and merging."""
import streamlit as st

from ekt.application import import_canonical_files, replace_supplier
from ekt.demo import DEMO_DATE, canonical_zip, demo_bundle
from ekt.partner import read_partner
from ekt_ui.state import load_bundle


@st.cache_data(show_spinner=False)
def cached_demo():
    return demo_bundle()


@st.cache_data(show_spinner=False)
def cached_partner(data, name, supplier, report_date, scope, meaning, base_units):
    return read_partner(data, name, supplier, report_date, scope, meaning, base_units)


def attempt_import(loader, label):
    # Publish only after every file has been parsed and merged successfully.
    try:
        bundle = loader()
    except Exception as exc:
        st.session_state.import_result = {
            "ok": False,
            "message": f"Ошибка импорта ({label}): {str(exc) or type(exc).__name__}",
            "retained": "bundle" in st.session_state,
        }
        return
    load_bundle(bundle)
    st.session_state.import_result = {
        "ok": True,
        "message": f"{label}: файлы прочитаны, текущий набор обновлён локально.",
    }


def render_import_result():
    result = st.session_state.get("import_result")
    if result is None:
        return
    if result["ok"]:
        st.success(result["message"])
    else:
        st.error(result["message"])
        if result["retained"]:
            st.info("Ранее загруженный набор сохранён без изменений и остаётся доступен.")
        else:
            st.info("Набор не загружен. Исправьте файл или параметры импорта и повторите попытку.")


def render_partner_import():
    st.caption("Адаптеры по аудиту; пока проверены только на макетах. Загрузите весь ZIP одного поставщика.")
    supplier = st.selectbox("Поставщик архива", ["IEK", "Systeme"])
    report_date = st.date_input("Дата выгрузки", DEMO_DATE.date())
    scope_confirmed = st.checkbox("Подтверждаю единую область всех отчётов и складов", value=False)
    scope_name = st.text_input("Название общей области", value="", disabled=not scope_confirmed)
    base_units = st.checkbox("Количество всех партий пути уже в базовых единицах", value=False)
    meaning = st.selectbox(
        "Поле MOQ IEK означает", ["unknown", "minimum", "multiple"],
        format_func=lambda x: {"unknown": "Не подтверждено", "minimum": "Минимальное количество", "multiple": "Кратность"}[x],
    ) if supplier == "IEK" else "multiple"
    upload = st.file_uploader("ZIP поставщика или один XLSX", type=["zip", "xlsx"])
    if st.button("Импортировать отчёты", disabled=upload is None, width="stretch"):
        def loader():
            if scope_confirmed and not scope_name.strip():
                raise ValueError("Введите название подтверждённой общей области")
            incoming = cached_partner(
                upload.getvalue(), upload.name, supplier, report_date,
                scope_name if scope_confirmed else None, meaning, base_units,
            )
            return replace_supplier(st.session_state.get("bundle"), incoming, supplier)

        attempt_import(loader, f"{supplier}, {upload.name}")


def render_canonical_import():
    mode_label = st.selectbox("Происхождение", ["Ручные / тестовые входы", "Данные партнёра", "Синтетические данные"])
    mode = {"Ручные / тестовые входы": "manual", "Данные партнёра": "partner", "Синтетические данные": "synthetic"}[mode_label]
    files = st.file_uploader(
        "Канонические ZIP, XLSX или CSV", type=["zip", "xlsx", "csv"],
        accept_multiple_files=True,
        help="Можно добавить недостающие таблицы после импорта отчётов. Каждая загружаемая таблица заменяет одноимённую целиком.",
    )
    append = st.checkbox("Дополнить текущий набор (заменить только загружаемые таблицы)", value=False)
    if st.button("Загрузить файлы", width="stretch", disabled=not files):
        def loader():
            previous = st.session_state.get("bundle") if append else None
            return import_canonical_files(
                ((uploaded.name, uploaded.getvalue()) for uploaded in files), mode, previous,
            )

        attempt_import(loader, ", ".join(uploaded.name for uploaded in files))


def render_imports():
    st.markdown("**Рабочий набор**")
    source = st.radio("Источник данных", ["Демонстрация", "Мои данные"])
    if source == "Демонстрация":
        st.caption("Четыре синтетических товара и известные контрольные события.")
        if st.button("Загрузить демо", icon=":material/science:", width="stretch"):
            load_bundle(cached_demo())
        st.download_button("Скачать демо для импорта", canonical_zip(cached_demo()), "synthetic_demo.zip", "application/zip", icon=":material/download:", type="tertiary", width="stretch")
    else:
        import_kind = st.selectbox("Формат", ["Канонические таблицы", "Отчёты IEK / Systeme"])
        if import_kind == "Отчёты IEK / Systeme":
            render_partner_import()
        render_canonical_import()
    render_import_result()
