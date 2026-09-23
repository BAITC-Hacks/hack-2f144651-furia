# Существующие интерфейсы EKT

Источник истины — код. Здесь описан API перед передачей задач. Имена функций в
`docs/kit/DATA_CONTRACTS.md` — исходное предложение, не повод создавать новые модули.

## Общие данные — LEAD

`src/ekt/schema.py`:

- `Bundle(tables={}, notes=[], mode="manual")`: dataclass с таблицами pandas;
  `bundle[name]` возвращает таблицу, `.copy()` копирует таблицы и notes.
  Отсутствующие таблицы создаются пустыми со столбцами SCHEMAS и PROVENANCE.
- Таблицы: products, sales, monthly_sales, stock_snapshots, inbound, stockouts,
  policies, growth_plan, seasonal_prior. Поля перечислены в SCHEMAS.
- KEY: supplier_id, sku_1c, warehouse_scope; products уникален по supplier_id/sku_1c.
  Идентификаторы — строки; даты после normalize — pandas datetime без времени;
  числовые поля — float, пропуски сохраняются.
- `normalize(bundle) -> Bundle`: копия с типами и происхождением. Неверное число
  или дата вызывает ValueError. unconfirmed_moq числовое; значение по-прежнему
  блокирует точный заказ до подтверждения семантики MOQ.
- `validate(bundle) -> list[str]`: пустой список означает отсутствие обнаруженных
  ошибок схемы, а не полноту всех бизнес-входов.
- `fingerprint(bundle, config=None) -> str`: отпечаток входов/параметров.
- `select(frame, key) -> DataFrame`: выборка по KEY.

PROVENANCE: source_file, source_sheet, source_row, data_mode. Режимы:
partner/synthetic/manual. Дополнительные столбцы допустимы, но normalize считает
их строками, если они не в NUMBERS/DATES. Новые числовые поля согласовать с LEAD.

## Импорт — DATA

- `ingest.read_canonical(data: bytes, filename: str, mode="manual") -> Bundle`:
  ZIP с именованными CSV, XLSX с каноническими листами или отдельный CSV.
  Неполный набор разрешён для редактирования; полная валидация при расчёте.
- `ingest.merge_tables(base, addition) -> Bundle`: непустая таблица addition
  заменяет одноимённую целиком; это не объединение отдельных строк.
- `partner.read_partner(data, filename, supplier, report_date,
  confirmed_scope=None, iek_moq_meaning="unknown", inbound_base_units=False) -> Bundle`.
  supplier: IEK/Systeme; без подтверждения общий scope не присваивается произвольно.
  Возвращает partner Bundle и notes, не изменяя исходники.

Адаптеры не рассчитывают заказы. Недостающие данные, несовместимая схема и
противоречия источников должны быть видимы; клиентов/stockout не выдумывать.

## Спрос и прогноз — ENGINE

- `demand.build_demand(sales, monthly, stockouts, as_of,
  remove_oneoffs=True, compensate=True) -> DemandResult`. Входы одного KEY.
  Результат: daily, monthly, events, warnings.
- daily: календарный DatetimeIndex; raw, excluded, stockout, covered, regular,
  imputed, corrected. monthly: DatetimeIndex начала месяца; raw, excluded,
  imputed, corrected, covered_days, days, complete.
- `forecast.forecast(demand, as_of, horizon, prior=None, growth=None)
  -> ForecastResult`: daily (Series будущих дней), seasonal_factors,
  seasonal_source, slope_per_month, training_end, warnings. Первый день — as_of+1.
- `engine.order_quantity(demand, safety, available, inbound, multiple, minimum=0)
  -> (net_need, recommended_qty)`. T1: `(100,20,30,25,10)` → `(65,70)`.
- `engine.calculate(bundle, as_of, remove_oneoffs=True, compensate=True)
  -> Calculation(rows, details, fingerprint, config)`. Ошибка схемы — ValueError;
  недостаток данных позиции — строка с NaN recommended_qty и объяснением.

Rows содержит row_id, ключи, unit/category_id, recommended_qty, urgency, explanation,
data_warnings, assumptions и компоненты успешного расчёта. Details индексируется
row_id и содержит demand, forecast, policy, если этап прогноза выполнен. При ранней
ошибке для row_id записи в details может не быть; balance/source_refs добавляются
при успешном расчёте заказа. UI использует их напрямую: формы не менять без LEAD. В движке нет чтения
Excel, Streamlit session state или внешних API.

## Решение менеджера и экспорт — LEAD

- `review.initial_edits(rows) -> DataFrame`: row_id, selected, adjusted_qty, reason.
- `review.approve(calculation, edits) -> Approval(signature, approved_at)`:
  выбранные строки валидны; изменённое количество требует причины.
- `review.export_frame(calculation, edits, approval=None) -> DataFrame`:
  final_qty, manager_override, draft/approved. Ноль — настоящее ручное решение.
  Изменение входов/правок делает старую подпись утверждения недействительной.
- `export.csv_bytes(frame, separator=";") -> bytes`;
  `export.xlsx_bytes(frame, metadata=None) -> bytes`.
- `demo.demo_bundle() -> Bundle`, `demo.canonical_zip(bundle) -> bytes`,
  `demo.DEMO_DATE = 2026-09-22`; демо всегда synthetic.

Экспорт не отправляет заказ; числа и единицы берутся из результата расчёта,
опасный текст экранируется, XLSX сохраняет SKU текстом.
