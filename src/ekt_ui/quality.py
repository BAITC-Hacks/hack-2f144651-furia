"""Actionable queues built from existing validation and engine diagnostics."""
import streamlit as st

from ekt.export import csv_bytes
from ekt_ui.presentation import deliveries


def render_quality(calculation):
    st.subheader("Очередь проверки")
    if calculation is None:
        st.info("Замечания по позициям появятся после расчёта. Проверка структуры набора доступна выше.")
        return
    rows = calculation.rows
    mask = rows.recommended_qty.isna() | rows.data_warnings.fillna("").ne("")
    checks = rows.loc[mask, ["supplier_id", "sku_1c", "name", "warehouse_scope", "recommended_qty", "explanation", "data_warnings"]].copy()
    checks["status"] = checks.recommended_qty.isna().map({True: "Расчёт заблокирован", False: "Требует проверки"})
    if checks.empty:
        st.success("В текущем расчёте нет позиций с предупреждениями.")
        return
    st.dataframe(checks, hide_index=True, width="stretch", column_order=["status", "supplier_id", "sku_1c", "name", "warehouse_scope", "data_warnings"],
                 column_config={"status": "Статус", "supplier_id": "Поставщик", "sku_1c": "Код 1С", "name": "Товар", "warehouse_scope": "Область", "data_warnings": st.column_config.TextColumn("Замечания", width="large")})
    st.download_button("Выгрузить замечания", csv_bytes(checks), "data_checks.csv", "text/csv", icon=":material/download:")


def render_deliveries(bundle, as_of):
    st.subheader("Поставки и подтверждение ETA")
    frame = deliveries(bundle, as_of)
    states = ["Все", "Ожидается", "Просрочена", "Нет ETA", "Не подтверждена", "Отменена"]
    state = st.selectbox("Статус поставки", states)
    if state != "Все":
        frame = frame.loc[frame.delivery_state.eq(state)]
    st.caption(f"Партий: {len(frame)} · Срез на {as_of:%d.%m.%Y} · Количества в разных единицах не суммируются")
    if frame.empty:
        st.info("Поставок по выбранным условиям нет.")
        return
    st.dataframe(frame[["delivery_state", "supplier_id", "sku_1c", "name", "warehouse_scope", "order_id", "qty_base_unit", "unit", "eta", "data_mode"]],
                 hide_index=True, width="stretch", height=min(520, 40 + 36 * len(frame)),
                 column_config={"delivery_state": "Статус", "supplier_id": "Поставщик", "sku_1c": "Код 1С", "name": "Товар", "warehouse_scope": "Область", "order_id": "Партия", "qty_base_unit": st.column_config.NumberColumn("В пути", format="%.2f"), "unit": "Ед.", "eta": st.column_config.DateColumn("ETA", format="DD.MM.YYYY"), "data_mode": "Источник"})
