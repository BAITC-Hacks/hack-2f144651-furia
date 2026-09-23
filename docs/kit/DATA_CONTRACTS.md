# Внутренние контракты и импорт

Это предлагаемые интерфейсы для быстрого согласования компонентов, не формат исходных файлов партнёра. Даты ISO 8601; количества — numeric; идентификаторы — строки; денежные значения не используются вместо количества. Все таблицы имеют `source_file`, `source_sheet`, `source_row`, `data_mode` (partner/synthetic/manual).

## Канонические таблицы

| Таблица | Поля и ключ |
|---|---|
| products | `supplier_id, sku_1c, supplier_sku, name, unit, category_id?`; уникальный `(supplier_id, sku_1c)`; category_source |
| sales | `supplier_id, sku_1c, warehouse_scope, date, document_id?, customer_id?, quantity_signed, unit, document_type`; сохранять original row ID, не терять возвраты |
| monthly_sales | `supplier_id, sku_1c, warehouse_scope, month, qty_net, is_complete, coverage_start, coverage_end`; ключ уникален |
| stock_snapshots | `supplier_id, sku_1c, warehouse_scope, as_of, on_hand?, reserved?, available?, snapshot_kind`; если есть available, резерв второй раз не вычитать |
| inbound | `supplier_id, sku_1c, warehouse_scope, order_id, qty_base_unit, eta?, eta_kind, status`; cancelled исключить; ETA unknown отдельно |
| stockouts | `supplier_id, sku_1c, warehouse_scope, start_date, end_date, evidence`; границы включительно, пересекающиеся интервалы объединять |
| policies | `supplier_id, category_id?, lead_time_days, review_days, safety_days, min_order_qty?, order_multiple?, unit_conversion?`; значения с origin: provided/manual/demo |
| growth_plan | `supplier_id, sku_1c? / category_id?, start_date, end_date, extra_growth_rate, source`; extra_growth_rate — дополнительное изменение относительно базовой модели; 0.1 означает +10% |
| seasonal_prior | `supplier_id, category_id?, month_of_year, factor, known_as_of, source`; 12 положительных конечных факторов, среднее 1 |

`warehouse_scope="UNSPECIFIED"` означает, что поле не было предоставлено; это не Алматы. `ALL_CONFIRMED` допустим только для согласованного общего пула. Смешение областей требует явного подтверждённого mapping.

Минимальные дополнительные CSV для отсутствующих входов: stockouts, policies, growth_plan, category_mapping, current_stock; плюс sales с анонимным customer_id для расширенной проверки. В интерфейсе показать образец ожидаемых колонок и ошибки по строкам.

## Выход одной строки

`supplier_id, sku_1c, supplier_sku, warehouse_scope, unit, category_id,
as_of, horizon_days, regular_demand, excluded_oneoff_qty,
imputed_lost_demand, expected_demand_horizon, safety_qty,
available_stock, inbound_within_horizon, inbound_late, inbound_unknown_eta,
net_need, recommended_qty, adjusted_qty?, approval_status,
urgency, explanation, data_warnings, assumptions, source_refs`.

`recommended_qty=null` означает недостаток обязательных входов; 0 означает посчитанное отсутствие потребности. Ручное `adjusted_qty=0` является настоящим нулём, не отсутствием override. Не сумма разных единиц как общий объём закупки.

## Предлагаемые интерфейсы Python

```python
load_partner_bundle(paths) -> RawBundle
normalize_bundle(raw, mappings, overrides) -> CanonicalBundle
validate_bundle(bundle) -> ValidationReport
build_regular_demand(bundle, config) -> DemandResult
forecast_demand(demand, as_of, horizon_days, config) -> ForecastResult
recommend_orders(bundle, forecast, config) -> RecommendationResult
export_orders(recommendations, selected_ids, format) -> bytes
```

Предпочитать чистые функции расчёта без Streamlit/API/чтения файлов внутри. UI читает результат, показывает объяснения, меняет inputs и вызывает пересчёт. ForecastResult содержит прогноз по дням, метод, cutoff и компоненты; RecommendationResult — все строки и предупреждения, а не только положительные заказы.

## Сверка и производительность

- Код 1С сохранять как текст до соединения. Не нечёткий join по имени товара по умолчанию. Не совпавшие коды — видимая таблица, не пропавшие строки.
- Структуру каждого отчёта определять по листу и заголовкам. Числа колонок в аудите помогают, но не заменяют проверку версии файла.
- В динамике исключить заголовки, строки без обязательных ключей и итоги с протоколом; классифицировать документы. Не удалять одинаковые строки автоматически: без line_id они могут быть реальными строками накладной.
- Месячные данные — авторитетный агрегат для 2024–2026 после проверки. Накладные — детализация для выбросов и сверки, не дополнительный объём. Исключённые по накладным количества вычитать из агрегата только на сопоставимом покрытии; расхождения показывать.
- Прочитать ~249 тысяч строк один раз. Кэшировать по хэшу файла и конфигурации, не перечитывать Excel на каждом движении ползунка. Прогноз векторизовать/агрегировать по SKU; не делать LLM-вызов на каждую строку.
- Сохранить загруженные факты неизменными; пользовательские допущения отдельным набором. Все расчёты должны быть воспроизводимы по входам и конфигурации.

## Экспорт

CSV UTF-8 с BOM и настраиваемым разделителем; XLSX с типизированными числами и текстовыми SKU. Включить код 1С, артикул поставщика, единицу, количество, обоснование, параметры и дату расчёта. Обезвредить текстовые значения, которые Excel мог бы интерпретировать как формулы; сохранить реальные числовые поля числами. До получения шаблона 1С говорить «экспорт для согласования/сопоставления», не «интеграция с 1С проверена».
