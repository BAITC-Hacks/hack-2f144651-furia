"""Calculation commands and filters for the purchasing workspace."""
import streamlit as st

from ekt.demo import DEMO_DATE
from ekt.engine import calculate
from ekt.schema import fingerprint, normalize
from ekt_ui.presentation import filter_orders
from ekt_ui.state import clear_review, invalidate_changed_inputs
from ekt_ui.workspace import reconcile_filters, render_view_tools


def render_calculation_options():
    as_of = st.date_input("Дата расчёта", DEMO_DATE.date(), help="Должна совпадать с датой подтверждённого текущего остатка.")
    remove_oneoffs = st.toggle("Исключать разовые заказы", value=True)
    compensate = st.toggle("Восстанавливать stockout", value=True, help="Только по явно введённым подтверждённым интервалам.")
    return as_of, remove_oneoffs, compensate


def render_calculation(bundle, as_of, remove_oneoffs, compensate):
    config = {"as_of": as_of.isoformat(), "remove_oneoffs": remove_oneoffs, "compensate": compensate}
    signature = fingerprint(normalize(bundle), config)
    if invalidate_changed_inputs(signature):
        st.session_state.input_notice = "Входы изменены. Расчёт и прежнее утверждение отменены."
    if st.button("Рассчитать предложения", type="primary", icon=":material/calculate:", width="stretch"):
        try:
            with st.spinner("Расчёт потребности"):
                calculation = calculate(bundle, as_of, remove_oneoffs, compensate)
            clear_review()
            st.session_state.calculation = calculation
            st.session_state.input_signature = signature
            st.session_state.calc_version = st.session_state.get("calc_version", 0) + 1
            st.session_state.pop("input_notice", None)
        except Exception as exc:
            st.error(str(exc))
    return st.session_state.get("calculation")


def reset_filters(categories, scopes):
    st.session_state.update(supplier_group="Все поставщики", order_search="",
                            order_categories=categories, order_scopes=scopes, order_risk="Все")


def render_filters(rows):
    suppliers = rows.supplier_id.unique().tolist()
    categories = rows.category_id.fillna("Не указана").unique().tolist()
    scopes = rows.warehouse_scope.unique().tolist()
    reconcile_filters(suppliers, categories, scopes)
    supplier_options = ["Все поставщики"] + suppliers
    saved_supplier = st.session_state.get("supplier_group", "Все поставщики")
    if saved_supplier not in supplier_options:
        supplier_options.append(saved_supplier)
    with st.container(key="filter_heading"):
        supplier_col, reset_col = st.columns([10, 1], vertical_alignment="center")
    with supplier_col:
        supplier = st.segmented_control("Поставщики", supplier_options,
                                       default="Все поставщики", required=True, key="supplier_group",
                                       label_visibility="collapsed",
                                       format_func=lambda value: value if value in ["Все поставщики", *suppliers] else f"{value} · нет в наборе")
    reset_col.button("Сбросить фильтры", icon=":material/filter_alt_off:", key="reset_filters",
                     help="Сбросить поиск и фильтры. Правки и выбор позиций сохраняются.", width=36,
                     on_click=reset_filters, args=(categories, scopes))
    search_col, category_col, scope_col, risk_col = st.columns([2.4, 1.2, 1.2, 1.5])
    search = search_col.text_input("Поиск товара", placeholder="Код 1С, артикул или название", icon=":material/search:", key="order_search")
    category_filter = category_col.multiselect("Категории", categories, default=categories, placeholder="Категории", key="order_categories")
    scope_filter = scope_col.multiselect("Области склада", scopes, default=scopes, placeholder="Области склада", key="order_scopes")
    risk = risk_col.selectbox("Уровень риска", ["Все", "Риск дефицита", "Критично", "Пополнение", "Норма", "Нужны данные", "Риск не определён", "Ручные правки"], key="order_risk", help="Критично: прогнозируемый дефицит менее чем через 7 дней. «Риск дефицита» включает только прогнозируемый дефицит; пополнение может быть нужно для страхового запаса.")
    render_view_tools(categories, scopes)
    return filter_orders(rows, suppliers if supplier == "Все поставщики" else [supplier],
                         scope_filter, category_filter, risk, search)
