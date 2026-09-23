"""Shared visual shell for the purchasing workspace."""
from pathlib import Path

import streamlit as st

from ekt_ui.presentation import deliveries


def configure_page():
    st.set_page_config(page_title="Электрокомплект | Заказы поставщикам", page_icon=":material/inventory_2:", layout="wide")
    css = Path(__file__).with_name("styles.css").read_text(encoding="utf-8")
    st.html(f"<style>{css}</style>")


def render_brand():
    with st.container(key="brand"):
        st.markdown(":material/electric_bolt: **Электрокомплект**")
        st.caption("EKT / Управление закупками")


def render_source(bundle):
    with st.container(key="source_banner", horizontal=True, vertical_alignment="center"):
        mode = bundle.mode
        st.badge({"synthetic": "Синтетические данные", "partner": "Данные партнёра", "manual": "Ручные данные"}.get(mode, mode),
                 color="orange" if mode == "synthetic" else "blue", icon=":material/database:")
        st.caption("Учебный набор, не сведения партнёра" if mode == "synthetic" else "Локальная обработка · отправка заказов не выполняется")


def render_kpis(calculation, bundle, as_of):
    rows = calculation.rows if calculation is not None else None
    risk = int(rows.urgency.eq("Риск дефицита").sum()) if rows is not None else "Нет расчёта"
    checks = int((rows.data_warnings.fillna("").ne("") | rows.recommended_qty.isna()).sum()) if rows is not None else "Нет расчёта"
    incoming = deliveries(bundle, as_of) if bundle is not None else None
    batches = int(incoming.delivery_state.eq("Ожидается").sum()) if incoming is not None else "Нет данных"
    cards = [
        ("risk", "Риск дефицита", risk, "Позиции с прогнозируемым отрицательным доступным остатком; каждый складской scope учитывается отдельно."),
        ("check", "Требует перепроверки", checks, "Позиции с предупреждениями движка или незавершённым расчётом. Это не число обнаруженных аномалий."),
        ("transit", "Партии в пути", batches, "Подтверждённые партии с ETA позже даты расчёта, включая поздние поставки. Разные единицы не суммируются."),
        ("value", "Общая сумма заказа", "Нет цен", "Закупочные цены и валюта отсутствуют в контракте. Денежная сумма не рассчитывается."),
    ]
    with st.container(key="kpi_band"):
        columns = st.columns(4)
    for column, (key, label, value, help_text) in zip(columns, cards):
        with column, st.container(key=f"kpi_{key}"):
            st.metric(label, value, help=help_text)
