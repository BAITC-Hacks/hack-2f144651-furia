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

## Карта Файлов

| Файлы | Назначение и владелец |
|---|---|
| app.py | Интегратор: стабильная точка запуска |
| src/ekt_ui/app.py, __init__.py, .streamlit/config.toml | Frontend: формы, графики, фильтры, состояние, тема |
| src/ekt/application.py | Backend: операции над наборами и provenance без UI |
| src/ekt/ingest.py | Backend: канонический импорт и объединение таблиц |
| src/ekt/partner.py | Backend: адаптеры IEK/Systeme |
| src/ekt/export.py | Backend: безопасные CSV/XLSX и метаданные |
| src/ekt/demo.py, data/demo/README.md | Backend: воспроизводимая синтетика |
| src/ekt/schema.py, __init__.py | Интегратор: общий контракт данных |
| src/ekt/demand.py | Logic: регулярный спрос, события и stockout |
| src/ekt/forecast.py | Logic: сезонность, тренд и план роста |
| src/ekt/engine.py | Logic: предложение, риск и объяснение |
| src/ekt/review.py | Logic: правки, утверждение, статус экспорта |
| tests/frontend/ | Frontend: Streamlit AppTest |
| tests/backend/ | Backend: операции application |
| tests/test_partner.py | Backend: синтетические схемы 12 отчётов |
| tests/test_acceptance.py | Logic: причинная приёмка M1-M5 |
| tests/test_edges.py | Backend/Logic: импорт, расчёт, краевые случаи |
| tests/test_workflow.py, tests/conftest.py | Интегратор: сквозной сценарий, общие фикстуры |
| scripts/smoke.py | Интегратор: CLI импорт -> расчёт -> правка -> утверждение -> экспорт |
| pyproject.toml, requirements.lock, setup.ps1, .gitignore | Интегратор: зависимости, окружение и запуск |
| README.md, THIRD_PARTY.md | Интегратор: вход в проект и лицензии |
| docs/INPUT_GUIDE.md | Backend: пользовательский ввод |
| docs/METHODOLOGY.md | Logic: формулы и объяснения |
| docs/DEMO.md | Frontend + интегратор: сценарий демонстрации |
| docs/DATA_LIMITATIONS.md | Backend + Logic: ограничения данных и модели |
| docs/STATUS.md, docs/VERIFICATION.md | Интегратор: состояние и история проверок |
| docs/kit/CASE_BRIEF.md, ACCEPTANCE.md | Исторические требования и исходная приёмка |
| docs/kit/DATA_CONTRACTS.md, DATA_AUDIT.md, ENGINE_SPEC.md | Исторические контракты, аудит и метод |
| AGENTS.md, вложенные AGENTS.md | Правила ролей соответствующих зон |
| docs/DEVELOPMENT.md, TASK_TEMPLATE.md, TASKS.md | Процесс, шаблон задачи и backlog |

docs/kit не является текущим backlog. Например, исходное ACCEPTANCE говорит, что
приложения ещё нет. Упоминание реальных архивов в DATA_AUDIT относится к исходному
комплекту: этих архивов в данном checkout нет. Актуальные задачи находятся в TASKS.

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

## Работа В Main И Приёмка

Для порученных Codex изменений работать прямо в `main`; feature-ветки не создавать,
если пользователь явно этого не попросил. Сначала проверить рабочее дерево, обновить
main fast-forward без переписывания истории, затем внести согласованные изменения.
Ветки и отдельные worktree допустимы только по прямому запросу пользователя или
для явно назначенного внешнего командного потока.

Для сквозной фичи согласовать общий контракт и одного интегратора. Соблюдать
назначенные роли и файлы из AGENT_PLAN; не редактировать чужую активную работу.
Не выполнять force push, reset --hard или переписывание чужих коммитов.

Рекомендуемые сообщения коммитов: feat(frontend): ..., fix(backend): ...,
feat(logic): ..., refactor(architecture): ..., test(integration): ..., docs(dev): ... .
Один коммит описывает одну проверяемую цель и включает её тесты. Перед коммитом
просмотреть diff; push выполнять по прямому поручению пользователя.

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
- BE-01/02: явно присутствующий пустой импорт очищает таблицу; источник сохраняется по однозначному содержимому, а не позиции.
- LOG-01/02: воспроизводимая оценка прогноза и строгая идентичность строк правок.
- D1/D2/D3: видимые конфликты месячных источников, корректные ETA и строгие числовые входы.
- INT-01: `.github/workflows/checks.yml`, Python 3.12, чистая среда Windows/Linux,
  locked install, pytest, smoke, pip check и синтетическая оценка. Фактические результаты в STATUS.
- Реальные архивы (BE-03/D4) отсутствуют. Постоянный журнал, многопользовательский режим
  и интеграция 1С остаются ограничениями MVP, отдельные согласованные задачи на них не выдавались.
