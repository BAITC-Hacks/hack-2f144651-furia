from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent / "src"))

import pandas as pd
import streamlit as st
from ekt.demo import demo_bundle, canonical_zip, DEMO_DATE
from ekt.schema import Bundle, SCHEMAS, PROVENANCE, normalize, validate, fingerprint
from ekt.ingest import read_canonical, merge_tables
from ekt.partner import read_partner
from ekt.engine import calculate
from ekt.review import initial_edits, approve, export_frame, review_signature
from ekt.export import csv_bytes, xlsx_bytes

st.set_page_config(page_title="EKT · Заказы поставщикам", page_icon="📦", layout="wide")
st.markdown("""<style>
.block-container {padding-top:2rem; max-width:1500px}
h1 {letter-spacing:-1.2px; font-weight:700 !important}
[data-testid="stMetric"] {background:white;border:1px solid #DBE5DF;padding:16px;border-radius:12px}
[data-testid="stMetricLabel"] {color:#63796E}
[data-testid="stSidebar"] {border-right:1px solid #DBE5DF}
.eyebrow {color:#17695B;letter-spacing:2px;font-size:12px;font-weight:700}
</style>""", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def cached_demo():
    return demo_bundle()


@st.cache_data(show_spinner=False)
def cached_import(data, name, mode):
    return read_canonical(data, name, mode)


@st.cache_data(show_spinner=False)
def cached_partner(data, name, supplier, report_date, scope, meaning, base_units):
    return read_partner(data, name, supplier, report_date, scope, meaning, base_units)


def load_bundle(bundle):
    st.session_state.bundle = bundle
    st.session_state.version = st.session_state.get("version", 0) + 1
    st.session_state.pop("calculation", None)
    st.session_state.pop("approval", None)
    st.session_state.pop("input_signature", None)


with st.sidebar:
    st.markdown("### EKT / закупки")
    st.caption("Локальный помощник менеджера")
    st.divider()
    source = st.radio("Источник данных", ["Демонстрация", "Мои данные"])
    if source == "Демонстрация":
        st.caption("Четыре синтетических товара и известные контрольные события.")
        if st.button("Загрузить демо", type="primary", width="stretch"):
            load_bundle(cached_demo())
        st.download_button("Скачать демо для импорта", canonical_zip(cached_demo()), "synthetic_demo.zip", "application/zip", width="stretch")
    else:
        import_kind = st.selectbox("Формат", ["Канонические таблицы", "Отчёты IEK / Systeme"])
        if import_kind == "Отчёты IEK / Systeme":
            st.caption("Адаптеры по аудиту; пока проверены только на макетах. Загрузите весь ZIP одного поставщика.")
            supplier = st.selectbox("Поставщик архива", ["IEK", "Systeme"])
            report_date = st.date_input("Дата выгрузки", DEMO_DATE.date())
            scope_confirmed = st.checkbox("Подтверждаю единую область всех отчётов и складов", value=False)
            scope_name = st.text_input("Название общей области", value="", disabled=not scope_confirmed)
            base_units = st.checkbox("Количество всех партий пути уже в базовых единицах", value=False)
            meaning = st.selectbox("Поле MOQ IEK означает", ["unknown", "minimum", "multiple"], format_func=lambda x: {"unknown": "Не подтверждено", "minimum": "Минимальное количество", "multiple": "Кратность"}[x]) if supplier == "IEK" else "multiple"
            partner_upload = st.file_uploader("ZIP поставщика или один XLSX", type=["zip", "xlsx"])
            if st.button("Импортировать отчёты", disabled=partner_upload is None, width="stretch"):
                try:
                    if scope_confirmed and not scope_name.strip():
                        raise ValueError("Введите название подтверждённой общей области")
                    incoming = cached_partner(partner_upload.getvalue(), partner_upload.name, supplier, report_date, scope_name if scope_confirmed else None, meaning, base_units)
                    previous = st.session_state.get("bundle")
                    if previous is not None and previous.mode == "partner":
                        for table_name in SCHEMAS:
                            retained = previous[table_name].loc[~previous[table_name].supplier_id.eq(supplier)]
                            incoming.tables[table_name] = pd.concat([retained, incoming[table_name]], ignore_index=True)
                        incoming.notes = list(dict.fromkeys(previous.notes + incoming.notes))
                    load_bundle(normalize(incoming))
                    st.success("Отчёты прочитаны. Проверьте ограничения и задайте недостающие параметры.")
                except Exception as exc:
                    st.error(f"Ошибка импорта: {exc}")
        mode_label = st.selectbox("Происхождение", ["Ручные / тестовые входы", "Данные партнёра", "Синтетические данные"])
        mode = {"Ручные / тестовые входы": "manual", "Данные партнёра": "partner", "Синтетические данные": "synthetic"}[mode_label]
        files = st.file_uploader("Канонические ZIP, XLSX или CSV", type=["zip", "xlsx", "csv"], accept_multiple_files=True, help="Можно добавить недостающие таблицы после импорта отчётов. Каждая загружаемая таблица заменяет одноимённую целиком.")
        append = st.checkbox("Дополнить текущий набор (заменить только загружаемые таблицы)", value=False)
        if st.button("Загрузить файлы", width="stretch", disabled=not files):
            try:
                combined = st.session_state.bundle.copy() if append and "bundle" in st.session_state else Bundle(mode=mode)
                for uploaded in files:
                    combined = merge_tables(combined, cached_import(uploaded.getvalue(), uploaded.name, mode))
                load_bundle(combined)
                st.success("Данные загружены локально")
            except Exception as exc:
                st.error(f"Ошибка импорта: {exc}")
    st.divider()
    as_of = st.date_input("Дата расчёта", DEMO_DATE.date(), help="Должна совпадать с датой подтверждённого текущего остатка.")
    remove_oneoffs = st.toggle("Исключать разовые заказы", value=True)
    compensate = st.toggle("Восстанавливать stockout", value=True, help="Только по явно введённым подтверждённым интервалам.")
    st.caption("Все вычисления на этом компьютере. Экспорт сохраняет файл; заказ поставщику не отправляется.")

st.markdown('<div class="eyebrow">ПЛАНИРОВАНИЕ ПОПОЛНЕНИЯ</div>', unsafe_allow_html=True)
st.title("Заказ, который можно объяснить")
st.write("От истории продаж к проверенному предложению по каждому поставщику.")

if "bundle" not in st.session_state:
    st.info("Выберите «Загрузить демо» слева или добавьте свои таблицы. Демо полностью синтетическое.")
    a, b, c = st.columns(3)
    a.markdown("#### 01 · Данные\nПродажи, текущий запас, путь и правила закупки.")
    b.markdown("#### 02 · Расчёт\nРегулярный спрос, сезонность, рост и подтверждённый дефицит.")
    c.markdown("#### 03 · Решение\nПроверка, корректировка, утверждение и CSV/XLSX.")
    st.stop()

bundle = st.session_state.bundle
version = st.session_state.version
if bundle.mode == "synthetic":
    st.warning("СИНТЕТИЧЕСКИЕ ДАННЫЕ · учебный пример, не сведения партнёра.")
else:
    st.info("Результат зависит от полноты входов. Неизвестные остатки и сроки блокируют заказ соответствующей позиции.")
for note in bundle.notes:
    if "СИНТЕТИЧЕСКИЕ" not in note:
        st.caption(note)

with st.expander("Входные таблицы и ручные параметры", expanded=False):
    st.caption("Редактируйте политику, категорию, остатки, план роста и подтверждённые интервалы. Идентификаторы — текст; даты YYYY-MM-DD. customer_id — только обезличенный. Изменения отменяют прежнее утверждение.")
    labels = {"products": "Товары / категории", "policies": "Сроки и кратность", "stock_snapshots": "Текущий запас", "inbound": "Путь", "growth_plan": "План роста", "stockouts": "Периоды дефицита", "sales": "Продажи / клиенты", "monthly_sales": "Месячная история", "seasonal_prior": "Сезонные коэффициенты"}
    name = st.selectbox("Таблица для просмотра и изменения", list(labels), format_func=lambda x: labels[x])
    st.caption(f"{name}: {len(bundle[name]):,} строк. Пропуск значения отличается от нуля.")
    frame = bundle[name]
    editable = frame[[col for col in frame.columns if col not in PROVENANCE]].copy()
    if len(frame) <= 15000:
        with st.form(f"inputs_{version}_{name}"):
            changed = st.data_editor(editable, num_rows="dynamic", width="stretch", key=f"data_{version}_{name}")
            saved = st.form_submit_button("Сохранить таблицу")
        if saved:
            try:
                updated = bundle.copy()
                # Preserve provenance only for rows that are unchanged; edits are explicit manual input.
                for col in PROVENANCE:
                    changed[col] = "manual" if col in ["source_file", "data_mode"] else name if col == "source_sheet" else ""
                for i in range(min(len(changed), len(frame))):
                    if changed.loc[i, editable.columns].equals(editable.iloc[i]):
                        for col in PROVENANCE:
                            changed.loc[i, col] = frame.iloc[i][col]
                updated.tables[name] = changed
                load_bundle(normalize(updated))
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    else:
        st.dataframe(editable.head(200), width="stretch")
        st.caption("Для больших таблиц показаны первые 200 строк. Исправьте CSV локально и загрузите заново.")
    st.download_button("Скачать текущие входы (ZIP)", canonical_zip(bundle), f"{bundle.mode}_inputs.zip", "application/zip")

config = {"as_of": as_of.isoformat(), "remove_oneoffs": remove_oneoffs, "compensate": compensate}
current_signature = fingerprint(normalize(bundle), config)
if st.session_state.get("input_signature") not in [None, current_signature]:
    st.session_state.pop("calculation", None)
    st.session_state.pop("approval", None)
    st.warning("Входы изменены. Предыдущее утверждение отменено; выполните расчёт заново.")

if st.button("Рассчитать предложения", type="primary"):
    try:
        with st.spinner("Сверяем историю и рассчитываем потребность…"):
            st.session_state.calculation = calculate(bundle, as_of, remove_oneoffs, compensate)
        st.session_state.input_signature = current_signature
        st.session_state.pop("approval", None)
        st.session_state.calc_version = st.session_state.get("calc_version", 0) + 1
    except Exception as exc:
        st.error(str(exc))

if "calculation" not in st.session_state:
    issues = validate(normalize(bundle))
    if issues:
        st.error("Исправьте входы перед расчётом:\n\n" + "\n\n".join(issues))
    st.stop()

calculation = st.session_state.calculation
rows = calculation.rows
m1, m2, m3, m4 = st.columns(4)
m1.metric("Поставщиков", rows.supplier_id.nunique())
m2.metric("Позиций к закупке", int(rows.recommended_qty.gt(0).sum()))
m3.metric("Риск дефицита", int(rows.urgency.eq("Риск дефицита").sum()))
m4.metric("Нужны данные", int(rows.recommended_qty.isna().sum()))
st.caption("Количество метров и штук не суммируется. Риск учитывает даты поступления уже заказанных партий.")

filter_left, filter_middle, filter_right = st.columns(3)
supplier_filter = filter_left.multiselect("Поставщики для просмотра", rows.supplier_id.unique().tolist(), default=rows.supplier_id.unique().tolist())
scope_options = rows.warehouse_scope.unique().tolist()
scope_filter = filter_middle.multiselect("Области склада", scope_options, default=scope_options)
category_options = rows.category_id.fillna("Не указана").unique().tolist()
category_filter = filter_right.multiselect("Категории", category_options, default=category_options)
visible = rows.loc[rows.supplier_id.isin(supplier_filter) & rows.warehouse_scope.isin(scope_filter) & rows.category_id.fillna("Не указана").isin(category_filter)]
summary_columns = ["supplier_id", "sku_1c", "name", "warehouse_scope", "unit", "recommended_qty", "urgency"]
st.dataframe(visible[summary_columns], hide_index=True, width="stretch", column_config={"supplier_id": "Поставщик", "sku_1c": "Код 1С", "name": "Товар", "warehouse_scope": "Область", "unit": "Ед.", "recommended_qty": st.column_config.NumberColumn("Рекомендовано", format="%.2f"), "urgency": "Приоритет"})

st.subheader("Объяснение позиции")
row_id = st.selectbox("Товар", rows.row_id.tolist(), format_func=lambda x: " · ".join(rows.loc[rows.row_id.eq(x), ["supplier_id", "sku_1c", "name"]].iloc[0].astype(str)))
row = rows.loc[rows.row_id.eq(row_id)].iloc[0]
st.write(row.explanation)
if row.data_warnings:
    st.warning(row.data_warnings)
st.caption(row.assumptions)
detail = calculation.details.get(row_id)
if detail:
    left, right = st.columns([2, 1])
    with left:
        st.caption("История по месяцам: факт и спрос после исключений / восстановления")
        st.line_chart(detail["demand"].monthly[["raw", "corrected"]].rename(columns={"raw": "Факт", "corrected": "Регулярный + восстановленный"}))
    with right:
        st.caption("Прогноз по дням")
        st.line_chart(detail["forecast"].daily)
    with st.expander("Компоненты, события и происхождение"):
        st.dataframe(pd.DataFrame([row]).T.astype("string").rename(columns={row.name: "Значение"}), width="stretch")
        if not detail["demand"].events.empty:
            st.write("Обнаруженные разовые события")
            st.dataframe(detail["demand"].events, hide_index=True, width="stretch")
        if "balance" in detail:
            st.write("Прогноз доступного остатка без нового заказа")
            st.line_chart(detail["balance"])
        st.json({"seasonal_source": detail["forecast"].seasonal_source, "factors": detail["forecast"].seasonal_factors, "training_end": detail["forecast"].training_end})

st.subheader("Проверка и экспорт")
st.caption("Отметьте позиции, при необходимости измените количество и укажите причину. Ноль — допустимое ручное решение. Фильтр просмотра выше не меняет состав экспорта.")
editor_frame = rows[["row_id", "supplier_id", "sku_1c", "unit", "recommended_qty"]].merge(initial_edits(rows), on="row_id")
edited = st.data_editor(editor_frame, hide_index=True, width="stretch", key=f"review_{st.session_state.calc_version}",
                        disabled=["row_id", "supplier_id", "sku_1c", "unit", "recommended_qty"],
                        column_config={"row_id": None, "supplier_id": "Поставщик", "sku_1c": "Код 1С", "unit": "Ед.", "recommended_qty": "Расчёт", "selected": "В экспорт", "adjusted_qty": st.column_config.NumberColumn("Заказать", min_value=0., format="%.2f"), "reason": "Причина изменения"})
edits = edited[["row_id", "selected", "adjusted_qty", "reason"]]
approval = st.session_state.get("approval")
if approval and approval.signature != review_signature(calculation, edits):
    st.session_state.pop("approval", None)
    approval = None
    st.info("Корректировка изменилась — утверждение отменено.")
if st.button("Утвердить выбранные позиции"):
    try:
        approval = approve(calculation, edits)
        st.session_state.approval = approval
    except ValueError as exc:
        st.error(str(exc))
if approval:
    st.success("Выбранные позиции утверждены локально. Отправка поставщику не выполнялась.")
else:
    st.caption("Статус: черновик. Можно скачать для проверки.")
try:
    exported = export_frame(calculation, edits, approval)
    if not exported.empty:
        a, b, c = st.columns([1, 1, 2])
        separator = c.selectbox("Разделитель CSV", [";", ","])
        a.download_button("Скачать CSV", csv_bytes(exported, separator), f"orders_{as_of}.csv", "text/csv", width="stretch")
        b.download_button("Скачать XLSX", xlsx_bytes(exported, {"inputs_hash": calculation.fingerprint, "configuration": calculation.config, "mode": bundle.mode, "notice": "Local review export; not a supplier submission"}), f"orders_{as_of}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
except ValueError as exc:
    st.error(str(exc))
