"""Calculation controls and read-only presentation of engine results."""
import pandas as pd
import streamlit as st

from ekt.demo import DEMO_DATE
from ekt.engine import calculate
from ekt.schema import fingerprint, normalize
from ekt_ui.state import invalidate_changed_inputs


def render_calculation_options():
    st.divider()
    as_of = st.date_input("Дата расчёта", DEMO_DATE.date(), help="Должна совпадать с датой подтверждённого текущего остатка.")
    remove_oneoffs = st.toggle("Исключать разовые заказы", value=True)
    compensate = st.toggle("Восстанавливать stockout", value=True, help="Только по явно введённым подтверждённым интервалам.")
    st.caption("Все вычисления на этом компьютере. Экспорт сохраняет файл; заказ поставщику не отправляется.")

    return as_of, remove_oneoffs, compensate


def render_calculation(bundle, as_of, remove_oneoffs, compensate):
    config = {"as_of": as_of.isoformat(), "remove_oneoffs": remove_oneoffs, "compensate": compensate}
    current_signature = fingerprint(normalize(bundle), config)
    if invalidate_changed_inputs(current_signature):
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

    return st.session_state.get("calculation")


def render_results(calculation):
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
