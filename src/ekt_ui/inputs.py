"""Current input diagnostics and the editable table scenario."""
import pandas as pd
import streamlit as st

from ekt.application import edit_table
from ekt.demo import canonical_zip
from ekt.schema import PROVENANCE, normalize, validate
from ekt_ui.state import load_bundle


def render_bundle_status(bundle):
    if bundle.mode == "synthetic":
        st.warning("СИНТЕТИЧЕСКИЕ ДАННЫЕ · учебный пример, не сведения партнёра.")
    st.caption(f"Происхождение набора: {bundle.mode}")
    for note in bundle.notes:
        st.caption(note)

    issues = validate(normalize(bundle))
    with st.expander("Состав и проверка текущего набора", expanded=bool(issues)):
        summary = pd.DataFrame([
            {
                "Таблица": name,
                "Строк": len(frame),
                "Происхождение строк": ", ".join(sorted(frame["data_mode"].dropna().unique())) or "Нет строк",
            }
            for name, frame in bundle.tables.items()
        ])
        st.dataframe(summary, hide_index=True, width="stretch")
        if issues:
            st.error("Исправьте входы перед расчётом:\n\n" + "\n\n".join(issues))
        else:
            st.info("Проверка validate: ошибок структуры не обнаружено.")
        st.caption("Число строк и результат validate не подтверждают полноту истории, остатков или сроков. Неизвестные значения не заменяются нулём.")


def render_inputs(bundle):
    version = st.session_state.version
    with st.expander("Входные таблицы и ручные параметры", expanded=False):
        st.caption("Редактируйте политику, категорию, остатки, план роста и подтверждённые интервалы. Идентификаторы — текст; даты YYYY-MM-DD. customer_id — только обезличенный. Изменения отменяют прежнее утверждение.")
        labels = {"products": "Товары / категории", "policies": "Сроки и кратность", "stock_snapshots": "Текущий запас", "inbound": "Путь", "growth_plan": "План роста", "stockouts": "Периоды дефицита", "sales": "Продажи / клиенты", "monthly_sales": "Месячная история", "seasonal_prior": "Сезонные коэффициенты"}
        name = st.selectbox("Таблица для просмотра и изменения", list(labels), format_func=lambda x: labels[x])
        st.caption(f"{name}: {len(bundle[name]):,} строк. Пропуск значения отличается от нуля.")
        frame = bundle[name]
        editable = frame[[col for col in frame.columns if col not in PROVENANCE]].copy()
        if len(frame) <= 15000:
            with st.form(f"inputs_{version}_{name}"):
                changed = st.data_editor(editable, num_rows="dynamic", width="stretch", key=f"data_{version}_{name}")
                saved = st.form_submit_button("Сохранить таблицу")
            if saved:
                try:
                    load_bundle(edit_table(bundle, name, changed))
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
        else:
            st.dataframe(editable.head(200), width="stretch")
            st.caption("Для больших таблиц показаны первые 200 строк. Исправьте CSV локально и загрузите заново.")
        st.download_button("Скачать текущие входы (ZIP)", canonical_zip(bundle), f"{bundle.mode}_inputs.zip", "application/zip")
