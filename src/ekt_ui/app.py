"""Streamlit entry orchestration; scenario modules own their controls."""
import streamlit as st

from ekt_ui.imports import render_imports
from ekt_ui.inputs import render_bundle_status, render_inputs
from ekt_ui.results import render_calculation, render_calculation_options, render_results
from ekt_ui.review import render_review


def main():
    st.set_page_config(page_title="EKT · Заказы поставщикам", page_icon="📦", layout="wide")
    st.markdown("""<style>
    .block-container {padding-top:2rem; max-width:1500px}
    h1 {letter-spacing:-1.2px; font-weight:700 !important}
    [data-testid="stMetric"] {background:white;border:1px solid #DBE5DF;padding:16px;border-radius:12px}
    [data-testid="stMetricLabel"] {color:#63796E}
    [data-testid="stSidebar"] {border-right:1px solid #DBE5DF}
    .eyebrow {color:#17695B;letter-spacing:2px;font-size:12px;font-weight:700}
    </style>""", unsafe_allow_html=True)

    with st.sidebar:
        render_imports()
        as_of, remove_oneoffs, compensate = render_calculation_options()

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
    render_bundle_status(bundle)
    render_inputs(bundle)
    calculation = render_calculation(bundle, as_of, remove_oneoffs, compensate)
    if calculation is None:
        st.stop()
    render_results(calculation)
    render_review(calculation, bundle.mode, as_of)
