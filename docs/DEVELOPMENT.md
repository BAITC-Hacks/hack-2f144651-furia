# Разработка По Зонам

## Архитектура

EKT является локальным Streamlit-приложением. Frontend и Backend работают в одном
Python-процессе; HTTP API, базы данных и постоянного хранения сессии пока нет.
Переход на отдельный веб-клиент/API будет самостоятельной фичей.

```text
app.py -> ekt_ui.app.main (widgets, cache, session_state)
                   +-> ekt.application -> ingest / schema
                   +-> ekt.partner / demo (input adapters)
                   +-> ekt.engine -> demand / forecast / schema
                   +-> ekt.review (approval / export_frame)
                   +-> ekt.export (CSV / XLSX bytes)
```

UI читает контракты и вызывает публичные функции ekt. Обратные импорты запрещены.
Состояние сессии принадлежит Frontend; допустимость утверждения и подпись правок
принадлежат Logic. Форматы файлов принадлежат Backend. Backend/Logic разделены
по модулям внутри существующего пакета ekt, а не на независимо запускаемые сервисы.

## Назначение модулей

Здесь описана архитектура, а не отдельная таблица разрешений. Единственное
распределение владельцев и исключений — в [AGENT_PLAN](AGENT_PLAN.md).

| Файлы | Назначение |
|---|---|
| app.py | Стабильная точка запуска |
| src/ekt_ui/app.py, __init__.py | Сборка рабочего экрана |
| src/ekt_ui/imports.py, inputs.py, state.py | Импорт в UI, входные таблицы и жизненный цикл сессии |
| src/ekt_ui/results.py, review.py | Запуск расчёта, фильтры, таблица правок, утверждение и скачивание |
| src/ekt_ui/presentation.py, details.py, quality.py | Представления, графики компонентов, очереди данных и поставок |
| src/ekt_ui/layout.py, styles.css, .streamlit/config.toml | Компоновка и адаптивная тема |
| src/ekt/application.py | Операции над наборами и provenance без UI |
| src/ekt/ingest.py, partner.py | Канонический импорт и адаптеры IEK/Systeme |
| src/ekt/export.py | Безопасные CSV/XLSX и метаданные |
| src/ekt/demo.py, data/demo/README.md | Воспроизводимая синтетика |
| src/ekt/schema.py, __init__.py | Общий контракт данных |
| src/ekt/demand.py | Регулярный спрос, события и stockout |
| src/ekt/forecast.py | Сезонность, тренд и план роста |
| src/ekt/engine.py | Предложение, риск и объяснение |
| src/ekt/review.py | Правки, утверждение, состав и статус экспортируемых строк |
| tests/frontend/, tests/backend/, тесты расчёта | Проверки поведения соответствующих модулей |
| tests/test_acceptance.py, test_edges.py, test_workflow.py, conftest.py | Общая приёмка M1–M5, края, сквозные сценарии и fixtures |
| scripts/smoke.py | CLI импорт → расчёт → правка → утверждение → экспорт |
| docs/INTERFACES.md | Описание существующего Python API |
| docs/TASKS.md, TASK_TEMPLATE.md | Актуальный backlog и конкретные назначения |
| docs/STATUS.md, VERIFICATION.md | Результаты и история проверок |

Архив docs/kit, [прежний план](history/AGENT_PLAN_LEGACY.md), старые handoff
и завершённые этапы STATUS не являются текущими назначениями. Например, исходное
ACCEPTANCE говорит, что приложения ещё нет. Актуальные задачи находятся в TASKS,
доступность оригиналов и оставшиеся ограничения — в свежих записях STATUS и
[DATA_LIMITATIONS](DATA_LIMITATIONS.md).

## Контракты

| Операция | Вход | Выход |
|---|---|---|
| import_canonical_files | пары (filename, bytes), mode, optional previous Bundle | новый Bundle |
| replace_supplier | previous или None, incoming Bundle, supplier | новый Bundle; другие partner-поставщики сохранены |
| edit_table | Bundle, имя таблицы, DataFrame без provenance | новый Bundle; однозначно совпадающие неизменённые строки сохраняют источник независимо от позиции |
| calculate | Bundle, as_of, remove_oneoffs, compensate | Calculation: rows, details, fingerprint, config |
| initial_edits / approve | rows / Calculation и edits | DataFrame правок / Approval |
| export_frame | Calculation, edits, optional Approval | выбранные строки со статусом draft/approved |
| csv_bytes / xlsx_bytes | DataFrame, параметры формата | bytes для скачивания |

Неполные данные позиции могут возвращать пустой recommended_qty и объяснение;
структурные ошибки и недопустимые правки дают ValueError. Контракт сейчас
Python/DataFrame, не JSON API. UI использует row_id, supplier_id, sku_1c,
warehouse_scope, unit, recommended_qty, explanation и поля details.
Изменение схемы требует согласования потребителей и проверки импорта, расчёта,
UI и экспорта. Функции изменения входов не мутируют исходный Bundle или кеш UI.

## Работа в main и приёмка

Назначения, границы файлов и приёмка определены в [AGENT_PLAN](AGENT_PLAN.md).
Порядок обновления main, commit/push и сохранения чужой работы — в
[корневых AGENTS](../AGENTS.md#git). В общем дереве Git выполняет интегратор;
исполнители передают проверенные изменения назначенных файлов.

Рекомендуемые сообщения коммитов: feat(frontend): ..., fix(backend): ...,
feat(logic): ..., refactor(architecture): ..., test(integration): ..., docs(dev): ... .
Один коммит описывает одну проверяемую цель. После каждого завершённого и
проверенного изменения, включая документацию, выполняются commit и push.

## История Коммитов

Срез первоначального проекта на 0ea01e6 содержал шесть коммитов:

| Коммит | Содержание | Вывод |
|---|---|---|
| c04f6c5 | Исходный README команды | Начальная история |
| bf5df48 | MVP, UI, расчёт, тесты, зависимости; 22 файла | Все слои появились крупным этапом |
| 19f0ec8 | Адаптеры, приёмка, UI/ядро; 12 файлов | Зоны менялись совместно |
| f2f0ac1 | Merge историй реализации и команды | Сохраняет обе истории |
| 541a8c4 | Краевые случаи, UI, ядро, инструкции; 14 файлов | Смешанные изменения нескольких зон |
| 0ea01e6 | STATUS и VERIFICATION | Отдельный документирующий коммит |

Позднее `main` продвинулся коммитом `10da4ac` (подготовка handoff и исправление
нормализации MOQ), затем merge `98333ed` добавил командные инструкции и тесты схемы.
Разделение слоёв перенесено в main отдельным коммитом после них. Описание точного
SHA и фактических тестов текущей ревизии находится в STATUS/VERIFICATION.
## Интегрированные доработки и ограничения

- FE-01/02: UI разделён на imports/inputs/results/review/state; ошибка импорта сохраняет прежний набор.
- FE-03: обновлён dashboard; возможности и предложения описаны в [DASHBOARD.md](DASHBOARD.md).
- Для таблицы правок источник истины — `session_state.review_edits`, ключ — `row_id`, а не номер видимой строки. Фильтр не меняет состав экспорта. При смене представления редактор получает новую ревизию.
- CSS использует `data-testid` Streamlit: после обновления версии нужно повторять визуальную проверку desktop/mobile и диалога.
- BE-01/02: явно присутствующий пустой импорт очищает таблицу; источник сохраняется по однозначному содержимому, а не позиции.
- LOG-01/02: воспроизводимая оценка прогноза и строгая идентичность строк правок.
- D1/D2/D3: видимые конфликты месячных источников, корректные ETA и строгие числовые входы.
- INT-01: `.github/workflows/checks.yml`, Python 3.12, чистая среда Windows/Linux,
  locked install, pytest, smoke, pip check и синтетическая оценка. Фактические результаты в STATUS.
- Сверка оригиналов BE-03 выявила ошибки IEK и конфликт MOQ Systeme; подробности в [handoff Backend](handoffs/backend.md). Успешный полный импорт и бизнес-входы требуют дальнейшей приёмки.
- Постоянный журнал, многопользовательский режим и интеграция 1С остаются ограничениями MVP; предложения, но не реализация — в DASHBOARD.
