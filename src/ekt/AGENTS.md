# Backend И Logic

Здесь нет UI, session_state, Streamlit, сетевых вызовов и глобального состояния сессии.
Пакет используется интерфейсом, CLI smoke и тестами напрямую.

## Backend

- application.py: импорт набора, замена поставщика, сохранение ручной таблицы и provenance.
- ingest.py: канонические ZIP/CSV/XLSX, ограничения архивов и объединение таблиц.
- partner.py: адаптеры IEK/Systeme, заголовки, даты, единицы, исходные допущения.
- export.py: безопасные CSV/XLSX, текстовые SKU, метаданные расчёта.
- demo.py: воспроизводимые синтетические данные и ZIP входов.
- Функции изменения набора возвращают новую копию, не меняют входы или кеш клиента.
- Проверки: tests/backend/, tests/test_partner.py, импорт/экспорт в tests/test_edges.py,
  tests/test_workflow.py и scripts/smoke.py.

## Logic

- demand.py: продажи/возвраты, разовые события, месячная сверка, stockout.
- forecast.py: сезонность, тренд, cutoff и дополнительный рост.
- engine.py: политика, горизонт, остаток/путь, MOQ/кратность, риск и объяснения.
- review.py: правки менеджера, причина, подпись утверждения и статус экспорта.
- Не читать файлы и не форматировать виджеты внутри расчётных функций.
- Изменение формулы требует причинного теста с известным результатом и обновления docs/METHODOLOGY.md.
- Проверки: tests/test_acceptance.py, tests/test_edges.py, tests/test_workflow.py.

## Общий Контракт

schema.py (Bundle, SCHEMAS, normalize, validate, fingerprint), Calculation,
DemandResult, ForecastResult и Approval согласуются с потребителями перед несовместимым изменением.
При разделении одной фичи Backend отвечает за ввод/вывод, Logic за числовое правило,
Frontend за отображение. Интегратор проверяет совместимость и полный пользовательский путь.
