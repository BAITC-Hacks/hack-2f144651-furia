"""Manager review and downloads, always independent of display filters."""
import streamlit as st

from ekt.export import csv_bytes, xlsx_bytes
from ekt.review import approve, export_frame, initial_edits, review_signature


def render_review(calculation, mode, as_of):
    rows = calculation.rows
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
            b.download_button("Скачать XLSX", xlsx_bytes(exported, {"inputs_hash": calculation.fingerprint, "configuration": calculation.config, "mode": mode, "notice": "Local review export; not a supplier submission"}), f"orders_{as_of}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
    except ValueError as exc:
        st.error(str(exc))
