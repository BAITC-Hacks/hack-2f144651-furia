"""Persistent manager edits, filtered grid, approval and local downloads."""
import pandas as pd
import streamlit as st

from ekt.export import csv_bytes, xlsx_bytes
from ekt.review import approve, export_frame, initial_edits, review_signature
from ekt_ui.presentation import merge_visible_edits


EDIT_COLUMNS = ["row_id", "selected", "adjusted_qty", "reason"]


def current_edits(calculation):
    if "review_edits" not in st.session_state:
        st.session_state.review_edits = initial_edits(calculation.rows)
    return st.session_state.review_edits


def publish_edits(calculation, edits):
    if review_signature(calculation, current_edits(calculation)) == review_signature(calculation, edits):
        return False
    st.session_state.review_edits = edits.copy()
    if st.session_state.pop("approval", None) is not None:
        st.session_state.review_notice = "Корректировка изменилась: утверждение отменено."
    st.session_state.review_revision = st.session_state.get("review_revision", 0) + 1
    return True


def grid_style(frame):
    style = pd.DataFrame("", index=frame.index, columns=frame.columns)
    colors = {"Критично": "#fff0f3", "Нужны данные": "#fff6dc", "Пополнение": "#eef3ff", "Норма": "#eaf7f1"}
    style["priority"] = frame.priority.map(lambda value: f"background-color: {colors[value]}; color: #303846; font-weight: 600")
    style.loc[frame.manual_edit.ne(""), "manual_edit"] = "background-color: #fff6dc; color: #8b5a00"
    return style


def render_order_grid(calculation, visible):
    edits = current_edits(calculation)
    context = tuple(visible.row_id)
    if st.session_state.get("review_context") != context:
        st.session_state.review_context = context
        st.session_state.review_revision = st.session_state.get("review_revision", 0) + 1
    with st.container(key="grid_tools"):
        info, mode_col, select_col, clear_col = st.columns([6, 3, .6, .6], vertical_alignment="center")
    info.caption(f"Показано {len(visible)} из {len(calculation.rows)} позиций")
    view = mode_col.segmented_control("Вид таблицы", ["Заказ", "Расчёт"], default="Заказ",
                                      required=True, key="order_view", label_visibility="collapsed")
    if select_col.button("Выбрать видимые", icon=":material/checklist:", help="Выбрать только показанные позиции с завершённым расчётом.", disabled=visible.empty, key="select_visible", width=36):
        changed = edits.copy()
        changed.loc[changed.row_id.isin(visible.loc[visible.recommended_qty.notna(), "row_id"]), "selected"] = True
        publish_edits(calculation, changed)
        st.rerun()
    if clear_col.button("Снять видимые", icon=":material/deselect:", help="Снять выбор только с показанных позиций.", disabled=visible.empty, key="unselect_visible", width=36):
        changed = edits.copy()
        changed.loc[changed.row_id.isin(visible.row_id), "selected"] = False
        publish_edits(calculation, changed)
        st.rerun()
    if visible.empty:
        st.info("Нет позиций по выбранным условиям. Выбор позиций для экспорта сохранён.")
        return
    columns = ["selected", "supplier_id", "sku_1c", "name", "priority", "unit"]
    if view == "Расчёт":
        columns += ["available_stock", "inbound_within_horizon", "expected_demand_horizon"]
    columns += ["recommended_qty", "adjusted_qty", "reason", "manual_edit", "history", "row_id"]
    frame = visible[columns].reset_index(drop=True)
    key = f"review_{st.session_state.calc_version}_{st.session_state.get('review_revision', 0)}_{view}"
    st.session_state.review_editor_key = key
    edited = st.data_editor(
        frame.style.apply(grid_style, axis=None), hide_index=True, width="stretch",
        height=min(500, max(150, 42 * len(frame) + 40)), row_height=42, key=key,
        disabled=[name for name in columns if name not in ("selected", "adjusted_qty", "reason")],
        column_config={
            "row_id": None,
            "selected": st.column_config.CheckboxColumn("Выбор", width=46),
            "sku_1c": st.column_config.TextColumn("Код 1С", width=88),
            "name": st.column_config.TextColumn("Товар", width=196),
            "priority": st.column_config.TextColumn("Срочность", width=100),
            "unit": st.column_config.TextColumn("Ед.", width=42),
            "available_stock": st.column_config.NumberColumn("Доступно", width=90, format="%.1f", help="Подтверждённый доступный остаток после резерва."),
            "inbound_within_horizon": st.column_config.NumberColumn("В пути", width=85, format="%.1f", help="Подтверждённые партии, которые движок учёл в горизонте. ETA и исключённые партии доступны в «Почему столько?»."),
            "expected_demand_horizon": st.column_config.NumberColumn("Прогноз", width=90, format="%.1f"),
            "recommended_qty": st.column_config.NumberColumn("Реком.", width=85, format="%.2f"),
            "adjusted_qty": st.column_config.NumberColumn("Заказать", width=90, min_value=0.0, format="%.2f", help="Ноль допустим. Изменение количества требует причины перед утверждением."),
            "history": st.column_config.LineChartColumn("Продажи, 6 мес.", width=104, help="Фактические месячные продажи, без повторного суммирования детализации."),
            "manual_edit": st.column_config.TextColumn("Правка", width=110),
            "reason": st.column_config.TextColumn("Причина изменения", width=180),
            "supplier_id": st.column_config.TextColumn("Поставщик", width=90),
        },
    )
    merged = merge_visible_edits(edits, edited[EDIT_COLUMNS])
    if publish_edits(calculation, merged):
        # Rebase the widget after an edit so later filters cannot replay stale row deltas.
        st.rerun()


def render_downloads(calculation, mode, as_of):
    edits = current_edits(calculation)
    approval = st.session_state.get("approval")
    try:
        exported = export_frame(calculation, edits, approval)
    except ValueError as exc:
        st.error(str(exc))
        return
    if exported.empty:
        st.caption("Нет выбранных позиций")
        return
    separator = st.selectbox("Разделитель CSV", [";", ","])
    st.download_button("Скачать CSV", csv_bytes(exported, separator), f"orders_{as_of}.csv", "text/csv", icon=":material/download:", width="stretch")
    st.download_button("Скачать XLSX", xlsx_bytes(exported, {
        "inputs_hash": calculation.fingerprint, "configuration": calculation.config, "mode": mode,
        "notice": "Local review export; not a supplier submission",
    }), f"orders_{as_of}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", icon=":material/download:", width="stretch")
    st.caption(f"{len(exported)} позиций · {'Утверждено' if approval else 'Черновик'}")
    st.caption("CSV/XLSX. Шаблон загрузки в 1С не согласован.")


def render_order_actions(calculation, visible_ids):
    edits = current_edits(calculation)
    approval = st.session_state.get("approval")
    if approval and approval.signature != review_signature(calculation, edits):
        st.session_state.pop("approval", None)
        approval = None
    if notice := st.session_state.pop("review_notice", None):
        st.info(notice)
    selected = edits.loc[edits.selected.fillna(False)]
    hidden = int((~selected.row_id.isin(visible_ids)).sum())
    with st.container(key="order_actions"):
        summary, reset_col, approve_col = st.columns([3, 1.6, 2.4], vertical_alignment="center")
        with summary:
            st.markdown(f"**Выбрано позиций: {len(selected)}**")
            st.caption(f"Скрыто фильтрами: {hidden} · Сумма заказа: нет закупочных цен")
        if reset_col.button("Сбросить изменения", icon=":material/undo:", width="stretch"):
            publish_edits(calculation, initial_edits(calculation.rows))
            st.session_state.pop("approval", None)
            st.rerun()
        if approve_col.button("Утвердить выбранные позиции", icon=":material/check_circle:", type="primary", width="stretch", disabled=selected.empty):
            try:
                st.session_state.approval = approve(calculation, edits)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if approval:
            st.success("Выбранные позиции утверждены локально. Отправка поставщику не выполнялась.")
        else:
            st.caption("Статус: черновик")
