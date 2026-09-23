"""Workspace guidance and view preferences; never changes purchasing decisions."""
from copy import deepcopy

import streamlit as st

from ekt.demo import demo_bundle
from ekt_ui.state import load_bundle


FILTER_KEYS = ("supplier_group", "order_search", "order_categories", "order_scopes", "order_risk")


def render_preferences():
    with st.expander("Рабочее пространство", icon=":material/settings:"):
        st.caption("Тема: меню ⋮ в правом верхнем углу → Light (светлая), Dark (тёмная) или System (как в системе).")
        st.radio("Плотность таблицы", ["Комфортная", "Компактная"], key="table_density", horizontal=True)
        st.caption("Фильтры и правки сохраняются в этой сессии. Перезагрузка страницы может их сбросить.")


def render_workflow(bundle, calculation):
    approved = calculation is not None and st.session_state.get("approval") is not None
    stage = 3 if approved else 2 if calculation is not None else 1 if bundle is not None else 0
    steps = ["Загрузите данные", "Рассчитайте", "Проверьте заказ", "Экспортируйте"]
    items = []
    for index, label in enumerate(steps):
        state = "done" if index < stage else "current" if index == stage else "next"
        marker = "✓" if index < stage else str(index + 1).zfill(2)
        current = ' aria-current="step"' if index == stage else ""
        items.append(f'<li class="{state}"{current}><span>{marker}</span>{label}</li>')
    st.html('<ol class="ekt-workflow" aria-label="Этапы подготовки заказа">' + "".join(items) + "</ol>")


def render_welcome():
    with st.container(key="welcome"):
        st.caption("ВАШ РАБОЧИЙ ДЕНЬ НАЧИНАЕТСЯ ЗДЕСЬ")
        st.header("От данных — к обоснованному заказу")
        st.write("Соберите продажи, остатки и поставки в одном месте. Проверьте рекомендации по каждой позиции и сохраните согласованный заказ.")
        st.button("Попробовать на демо", type="primary", icon=":material/play_arrow:",
                  on_click=load_bundle, args=(demo_bundle(),))
        st.caption("Синтетический набор · 2 поставщика · без API-ключа")
    columns = st.columns(3)
    for col, (icon, title, detail) in zip(columns, [
        ("upload_file", "01 / Подключите данные", "Загрузите файлы через боковую панель. Источники и ограничения видны в контроле данных."),
        ("query_stats", "02 / Разберите рекомендации", "Откройте «Почему столько?»: спрос, остаток, сроки и причины предложения."),
        ("task_alt", "03 / Примите решение", "Измените количество с пояснением, утвердите выбор и скачайте CSV или XLSX."),
    ]):
        with col, st.container(border=True):
            st.markdown(f":material/{icon}: **{title}**")
            st.caption(detail)


def reconcile_filters(suppliers, categories, scopes):
    """Drop unavailable saved values without silently broadening an empty selection."""
    state = st.session_state
    # Keep an absent supplier as an explicit empty filter; do not switch to all.
    for key, available in (("order_categories", categories), ("order_scopes", scopes)):
        if key in state:
            state[key] = [value for value in state[key] if value in available]


def apply_quick_view(risk, categories, scopes):
    st.session_state.update(supplier_group="Все поставщики", order_search="",
                            order_categories=categories, order_scopes=scopes, order_risk=risk)


def save_view():
    name = st.session_state.get("view_name", "").strip()
    views = dict(st.session_state.get("saved_views", {}))
    if not name:
        st.session_state.view_notice = "Укажите название представления."
        return
    if name not in views and len(views) >= 8:
        st.session_state.view_notice = "Можно сохранить до 8 представлений. Удалите ненужное или обновите существующее."
        return
    views[name] = {key: deepcopy(st.session_state.get(key)) for key in FILTER_KEYS}
    st.session_state.saved_views = views
    st.session_state.view_notice = f"Представление «{name}» сохранено в этой сессии."


def apply_saved_view(name):
    values = st.session_state.get("saved_views", {}).get(name, {})
    st.session_state.update(deepcopy(values))


def delete_saved_view(name):
    views = dict(st.session_state.get("saved_views", {}))
    views.pop(name, None)
    st.session_state.saved_views = views


def render_view_tools(categories, scopes):
    with st.container(key="quick_views", horizontal=True, vertical_alignment="center"):
        for label, risk, icon in [("Все позиции", "Все", "view_list"),
                                  ("Риск дефицита", "Риск дефицита", "priority_high"),
                                  ("Мои правки", "Ручные правки", "edit_note")]:
            st.button(label, key=f"quick_{risk}", icon=f":material/{icon}:",
                      help="Открыть эту подборку по всем поставщикам, категориям и складам.",
                      on_click=apply_quick_view, args=(risk, categories, scopes))
        with st.popover("Мои представления", icon=":material/bookmark:"):
            st.caption("Сохраняет поиск и фильтры в текущей сессии. Количества и выбранные позиции не меняются.")
            st.text_input("Название представления", key="view_name", max_chars=40, placeholder="Например, IEK · склад Алматы")
            st.button("Сохранить / обновить", on_click=save_view, width="stretch")
            views = st.session_state.get("saved_views", {})
            if views:
                name = st.selectbox("Сохранённые представления", list(views), key="saved_view_choice")
                left, right = st.columns(2)
                left.button("Применить", on_click=apply_saved_view, args=(name,), width="stretch")
                right.button("Удалить", on_click=delete_saved_view, args=(name,), width="stretch")
            if notice := st.session_state.pop("view_notice", None):
                st.info(notice)
