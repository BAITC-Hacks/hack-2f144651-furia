"""The purchasing workspace. Business operations remain in the ekt package."""
import streamlit as st

from ekt_ui.details import render_detail_launcher
from ekt_ui.imports import render_imports
from ekt_ui.inputs import render_bundle_status, render_inputs
from ekt_ui.layout import configure_page, render_brand, render_kpis, render_source
from ekt_ui.presentation import order_grid
from ekt_ui.quality import render_deliveries, render_quality
from ekt_ui.results import render_calculation, render_calculation_options, render_filters
from ekt_ui.review import current_edits, render_downloads, render_order_actions, render_order_grid
from ekt_ui.workspace import render_preferences, render_welcome, render_workflow


def main():
    configure_page()
    with st.sidebar:
        render_brand()
        with st.expander("Импорт данных", expanded=True, icon=":material/upload_file:"):
            render_imports()
        with st.expander("Параметры расчёта", expanded=False, icon=":material/tune:"):
            as_of, remove_oneoffs, compensate = render_calculation_options()
        render_preferences()
        st.caption(":material/lock: Локальное рабочее пространство")

    bundle = st.session_state.get("bundle")
    with st.container(key="workspace_header"):
        title, action = st.columns([4, 1.6], vertical_alignment="center")
        with title:
            st.caption("ЭЛЕКТРОКОМПЛЕКТ / ПЛАНИРОВАНИЕ")
            st.title("Заказы поставщикам")
            st.caption("Спрос, остатки и решения — в одном рабочем пространстве")
        with action:
            calculation = render_calculation(bundle, as_of, remove_oneoffs, compensate) if bundle is not None else None
            if bundle is None:
                st.button("Рассчитать предложения", disabled=True, type="primary", icon=":material/calculate:", width="stretch")
    if bundle is not None:
        render_source(bundle, as_of)
    if notice := st.session_state.pop("input_notice", None):
        st.warning(notice)
    render_workflow(bundle, calculation)
    if bundle is None:
        render_welcome()
        return
    render_kpis(calculation, bundle, as_of)
    order_tab, quality_tab, transit_tab, input_tab = st.tabs([
        ":material/receipt_long: Заказы", ":material/fact_check: Контроль данных",
        ":material/local_shipping: Поставки", ":material/table_view: Входные таблицы",
    ])
    visible_ids = []
    with order_tab:
        with st.container(key="orders_heading"):
            heading, export = st.columns([5, 1], vertical_alignment="center")
        heading.subheader("Предложения к заказу")
        with export, st.popover("Экспорт", icon=":material/download:", disabled=calculation is None, width="stretch"):
            if calculation is not None:
                render_downloads(calculation, bundle.mode, as_of)
        if calculation is not None:
            grid = order_grid(calculation, current_edits(calculation))
            with st.container(key="order_filters"):
                visible = render_filters(grid)
            visible_ids = visible.row_id.tolist()
            render_order_grid(calculation, visible)
            render_detail_launcher(calculation, bundle, visible)
        elif bundle is not None:
            st.info("Набор загружен. Предложения ещё не рассчитаны.")
        else:
            st.info("Нет загруженных данных. Доступны импорт файлов и синтетическое демо.")
    with quality_tab:
        if bundle is not None:
            render_bundle_status(bundle)
            render_quality(calculation)
        else:
            st.info("Набор данных не загружен.")
    with transit_tab:
        if bundle is not None:
            render_deliveries(bundle, as_of)
        else:
            st.info("Нет сведений о поставках.")
    with input_tab:
        if bundle is not None:
            render_inputs(bundle)
        else:
            st.info("Нет входных таблиц.")
    if calculation is not None:
        render_order_actions(calculation, visible_ids)
