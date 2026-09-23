"""Item-level explainability in a native, keyboard-accessible side dialog."""
import altair as alt
import pandas as pd
import streamlit as st

from ekt_ui.presentation import item_deliveries, number, urgency_label


def demand_chart(detail):
    monthly = detail["demand"].monthly.tail(12).copy()
    monthly.index.name = "month"
    data = monthly.reset_index()
    tooltip = [alt.Tooltip("month:T", title="Месяц", format="%m.%Y"),
               alt.Tooltip("raw:Q", title="Факт", format=".2f"),
               alt.Tooltip("corrected:Q", title="Очищенный спрос", format=".2f"),
               alt.Tooltip("excluded:Q", title="Исключено", format=".2f"),
               alt.Tooltip("imputed:Q", title="Восстановлено", format=".2f"),
               alt.Tooltip("complete:N", title="Полный месяц")]
    base = alt.Chart(data).encode(x=alt.X("month:T", title=None, axis=alt.Axis(format="%b %y")), tooltip=tooltip)
    raw = base.mark_line(color="#8c9bab", strokeWidth=2).encode(y=alt.Y("raw:Q", title="Количество"))
    corrected = base.mark_line(color="#159475", strokeWidth=2.5, strokeDash=[6, 3]).encode(y="corrected:Q")
    outliers = base.transform_filter(alt.datum.excluded > 0).mark_point(color="#de4964", size=80, filled=True).encode(y="raw:Q")
    return (raw + corrected + outliers).properties(height=220).interactive(bind_y=False)


@st.dialog("Аналитика позиции", width="large", on_dismiss="rerun")
def show_item(calculation, bundle, row_id):
    row = calculation.rows.loc[calculation.rows.row_id.eq(row_id)].iloc[0]
    st.caption(f"{row.supplier_id} / {row.sku_1c} / {row.warehouse_scope}")
    st.subheader(row["name"])
    status = urgency_label(row, calculation.config["as_of"])
    st.badge(status, color={"Критично": "red", "Нужны данные": "orange", "Пополнение": "blue", "Норма": "green"}[status])
    category = "Не указана" if pd.isna(row.category_id) else row.category_id
    unit = "Не указана" if pd.isna(row.unit) else row.unit
    st.caption(f"Категория: {category} · Единица: {unit} · ABC/XYZ: не рассчитаны")
    st.write(row.explanation)
    detail = calculation.details.get(row_id)
    if detail:
        for column, (label, field) in zip(st.columns(2), [("Прогноз на горизонт", "expected_demand_horizon"), ("Страховой запас", "safety_qty")]):
            column.metric(label, number(row.get(field)), help=f"Базовая единица: {row.unit}")
        for column, (label, field) in zip(st.columns(2), [("Доступный остаток", "available_stock"), ("Путь в горизонте", "inbound_within_horizon")]):
            column.metric(label, number(row.get(field)), help=f"Базовая единица: {row.unit}")
        st.metric("Рекомендованный заказ", number(row.recommended_qty), help="Количество после применения MOQ и кратности; ручная корректировка не меняет рекомендацию движка.")
        st.caption(f"Чистая потребность: {number(row.get('net_need'))} · MOQ: {number(detail['policy'].get('min_order_qty'))} · Кратность: {number(detail['policy'].get('order_multiple'))}")

    demand_tab, transit_tab, source_tab = st.tabs(["Спрос и прогноз", "Поставки", "Источники"])
    with demand_tab:
        if detail:
            st.altair_chart(demand_chart(detail), width="stretch")
            st.caption("Факт: серый · Очищенный спрос: зелёный пунктир · Месяцы с исключениями: красный")
            st.caption(f"За всю историю исключено: {number(row.get('excluded_oneoff_qty'))} {row.unit}; восстановлено: {number(row.get('imputed_lost_demand'))} {row.unit}. Эти объёмы не прибавляются повторно к прогнозу.")
            st.caption(f"Сезонность: {row.get('seasonal_source', 'Нет данных')}")
            st.line_chart(detail["forecast"].daily.rename("Прогноз"), height=180, color="#2855d9")
            if not detail["demand"].events.empty:
                with st.expander("Разовые события"):
                    st.dataframe(detail["demand"].events, hide_index=True, width="stretch")
            if "balance" in detail:
                with st.expander("Остаток без нового заказа"):
                    st.line_chart(detail["balance"].rename("Доступный остаток"), height=180, color="#df4562")
        else:
            st.info("Прогноз для позиции не построен. Причина указана в результате расчёта.")
    with transit_tab:
        incoming = item_deliveries(bundle, row)
        if incoming.empty:
            st.info("В текущем наборе нет партий для этой позиции и области склада.")
        else:
            st.dataframe(incoming[["order_id", "qty_base_unit", "unit", "eta", "delivery_state"]], hide_index=True,
                         column_config={"order_id": "Партия", "qty_base_unit": "Количество", "unit": "Ед.", "eta": st.column_config.DateColumn("ETA", format="DD.MM.YYYY"), "delivery_state": "Статус"}, width="stretch")
    with source_tab:
        if row.data_warnings:
            for warning in row.data_warnings.split(" | "):
                st.warning(warning)
        if row.assumptions:
            st.caption(row.assumptions)
        if detail:
            for reference in detail.get("source_refs", []):
                st.text(reference)
        st.caption(f"Расчёт: {calculation.fingerprint[:16]} · Режим: {bundle.mode}")


def render_detail_launcher(calculation, bundle, visible):
    left, right = st.columns([4, 1.5], vertical_alignment="bottom")
    options = visible.row_id.tolist()
    names = visible.set_index("row_id")
    row_id = left.selectbox("Товар", options, placeholder="Нет позиций в текущем фильтре", disabled=not options,
                            format_func=lambda value: f"{names.loc[value, 'sku_1c']} · {names.loc[value, 'name']}")
    if right.button("Почему столько?", icon=":material/info:", disabled=not options, width="stretch"):
        show_item(calculation, bundle, row_id)
